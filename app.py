"""Server-side API for Smart Campus Management using Supabase PostgreSQL."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from supabase import create_client

load_dotenv()
app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "change-this-before-deploying")

url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key) if url and key else None


def now(): return datetime.now(timezone.utc).isoformat()
def code_hash(value): return hashlib.sha256(value.strip().encode()).hexdigest()
def error(message, status=400): return jsonify({"error": message}), status
def client():
    if not supabase: raise RuntimeError("Supabase is not configured. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to .env.")
    return supabase
def signed_in(role=None):
    profile = session.get("profile")
    if not profile: return None
    return profile if not role or profile["role"] == role else None
def require(role=None):
    profile = signed_in(role)
    return profile or None


@app.errorhandler(RuntimeError)
def config_error(exc): return error(str(exc), 503)

@app.get("/")
def home(): return send_from_directory("templates", "index.html")

@app.get("/api/session")
def get_session(): return jsonify({"profile": session.get("profile")})

@app.post("/api/session")
def sign_in():
    """Stores a faculty/maintenance identity in Supabase; access code remains hashed."""
    data = request.get_json() or {}
    name, email, access_code = (data.get("name", "").strip(), data.get("email", "").strip().lower(), data.get("access_code", "").strip())
    role = data.get("role", "faculty")
    if not name or not email or not access_code or "@" not in email or role not in ("faculty", "worker"):
        return error("Enter a name, valid email, access code and role.")
    db = client(); existing = db.table("profiles").select("*").eq("email", email).execute().data
    if existing:
        profile = existing[0]
        if profile["name"].casefold() != name.casefold() or profile["access_code_hash"] != code_hash(access_code) or profile["role"] != role:
            return error("The supplied name, role or access code does not match this email.", 403)
    else:
        profile = db.table("profiles").insert({"name": name, "email": email, "role": role, "access_code_hash": code_hash(access_code)}).execute().data[0]
    session["profile"] = {"id": profile["id"], "name": profile["name"], "email": profile["email"], "role": profile["role"]}
    return jsonify({"profile": session["profile"]})

@app.delete("/api/session")
def sign_out(): session.clear(); return jsonify({"message": "Signed out."})

@app.get("/api/dashboard")
def dashboard():
    db = client(); rooms = db.table("rooms").select("capacity, benches, occupied_seats, status").execute().data
    issues = db.table("issues").select("id").neq("status", "Verified").execute().data
    return jsonify({"rooms": len(rooms), "available": sum(x["status"] == "Available" for x in rooms), "attention": sum(x["status"] == "Attention" for x in rooms), "empty": sum(x["status"] == "Empty" for x in rooms), "unavailable": sum(x["status"] == "Unavailable" for x in rooms), "benches": sum(x["benches"] for x in rooms), "seats": sum(x["capacity"] for x in rooms), "occupied": sum(x["occupied_seats"] for x in rooms), "open_issues": len(issues)})

@app.get("/api/rooms")
def rooms():
    term, category = request.args.get("q", ""), request.args.get("category", "")
    query = client().table("rooms").select("*").order("room_number")
    if category: query = query.eq("category", category)
    data = query.execute().data
    if term: data = [r for r in data if term.casefold() in f"{r['room_number']} {r['room_name']}".casefold()]
    return jsonify(data)

@app.get("/api/issues")
def issues():
    return jsonify(client().table("issues").select("*, rooms(room_number,room_name)").order("priority_rank", desc=True).order("created_at", desc=True).execute().data)

@app.post("/api/issues")
def report_issue():
    profile = require("faculty")
    if not profile: return error("Sign in as faculty to report an issue.", 401)
    data = request.get_json() or {}
    required = ("room_id", "title", "category", "priority", "description")
    if not all(data.get(field) for field in required): return error("Complete all issue fields.")
    rank = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}.get(data["priority"], 1)
    result = client().table("issues").insert({**{k:data[k] for k in required}, "priority_rank":rank, "reported_by":profile["id"], "created_at":now()}).execute().data
    return jsonify(result[0]), 201

@app.patch("/api/issues/<issue_id>/repair")
def repair(issue_id):
    profile = require("worker")
    if not profile: return error("Sign in as maintenance staff to update this issue.", 401)
    data = request.get_json() or {}; status = data.get("status")
    if status not in ("In Progress", "Resolved"): return error("Choose In Progress or Resolved.")
    client().table("issues").update({"status":status,"worker_note":data.get("worker_note", ""),"updated_at":now(),"assigned_to":profile["id"]}).eq("id", issue_id).execute()
    return jsonify({"message":"Maintenance update saved."})

@app.patch("/api/issues/<issue_id>/verify")
def verify(issue_id):
    profile = require("faculty")
    if not profile: return error("Sign in as faculty to verify this issue.", 401)
    data = request.get_json() or {}; verdict = data.get("verdict")
    issue = client().table("issues").select("reported_by").eq("id", issue_id).execute().data
    if not issue: return error("Issue not found.", 404)
    if issue[0]["reported_by"] != profile["id"]: return error("Only the reporting faculty member may verify or reopen this issue.", 403)
    if verdict not in ("Verified", "Reopened"): return error("Choose Verified or Reopened.")
    client().table("issues").update({"status":"Verified" if verdict == "Verified" else "Open", "faculty_verification":verdict, "updated_at":now()}).eq("id", issue_id).execute()
    return jsonify({"message":f"Issue {verdict.lower()}."})

@app.get("/api/subjects")
def subjects(): return jsonify(client().table("subjects").select("*, profiles(name)").order("semester").order("code").execute().data)

@app.get("/api/timetable")
def timetable(): return jsonify(client().table("timetable").select("*, rooms(room_number), subjects(code,name,credits), profiles(name)").order("day_order").order("start_time").execute().data)

@app.post("/api/timetable")
def add_timetable():
    profile = require("faculty")
    if not profile: return error("Sign in as faculty to create a timetable entry.", 401)
    data = request.get_json() or {}; fields=("day","day_order","start_time","end_time","room_id","section","subject_id")
    if not all(str(data.get(x,"")) for x in fields): return error("Complete all timetable fields.")
    subject = client().table("subjects").select("faculty_id").eq("id",data["subject_id"]).execute().data
    if not subject or subject[0]["faculty_id"] != profile["id"]: return error("Only the assigned lecturer can schedule this subject.",403)
    entries = client().table("timetable").select("*").eq("day",data["day"]).execute().data
    conflict = any(e["start_time"] < data["end_time"] and e["end_time"] > data["start_time"] and (e["room_id"] == data["room_id"] or e["section"] == data["section"] or e["faculty_id"] == profile["id"]) for e in entries)
    if conflict: return error("Clash found for this room, lecturer or section.", 409)
    output=client().table("timetable").insert({k:data[k] for k in fields}|{"faculty_id":profile["id"]}).execute().data[0]
    return jsonify(output),201

@app.get("/api/progress")
def progress(): return jsonify(client().table("syllabus_progress").select("*, subjects(code,name,credits,semester), profiles(name)").order("updated_at",desc=True).execute().data)

@app.post("/api/progress")
def add_progress():
    profile=require("faculty")
    if not profile:return error("Sign in as faculty to update syllabus coverage.",401)
    data=request.get_json() or {}; subject=client().table("subjects").select("faculty_id").eq("id",data.get("subject_id")).execute().data
    if not subject or subject[0]["faculty_id"] != profile["id"]:return error("Only the assigned lecturer can update this subject.",403)
    try: coverage=float(data["coverage_percent"])
    except (KeyError,ValueError,TypeError):return error("Coverage must be from 0 to 100.")
    if not 0<=coverage<=100 or not data.get("topics_covered") or not data.get("week_number"):return error("Complete week, coverage and topics.")
    record={"subject_id":data["subject_id"],"week_number":data["week_number"],"coverage_percent":coverage,"topics_covered":data["topics_covered"],"updated_by":profile["id"],"updated_at":now()}
    output=client().table("syllabus_progress").upsert(record,on_conflict="subject_id,week_number").execute().data[0]
    return jsonify(output),201

if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), debug=True)
