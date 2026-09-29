-- Smart Campus Management - fresh Supabase PostgreSQL schema
-- Run this file in Supabase Dashboard > SQL Editor. It deliberately contains no records.

create extension if not exists "pgcrypto";

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 2 and 100),
  email text not null unique check (email = lower(email)),
  role text not null check (role in ('faculty', 'worker')),
  access_code_hash text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.rooms (
  id uuid primary key default gen_random_uuid(),
  room_number text not null unique,
  room_name text not null,
  category text not null check (category in ('Classroom', 'Laboratory', 'Staff Room', 'HOD Room', 'Faculty Room', 'Seminar Hall', 'Toilet', 'Other')),
  floor text not null,
  capacity integer not null default 0 check (capacity >= 0),
  benches integer not null default 0 check (benches >= 0),
  occupied_seats integer not null default 0 check (occupied_seats >= 0 and occupied_seats <= capacity),
  projector text not null default 'Not applicable',
  board text not null default 'Not applicable',
  internet text not null default 'Not applicable',
  other_resources text not null default '',
  status text not null default 'Empty' check (status in ('Available', 'Attention', 'Unavailable', 'Empty')),
  created_at timestamptz not null default now()
);

create table if not exists public.subjects (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  semester integer not null check (semester between 1 and 8),
  credits numeric(3,1) not null check (credits > 0),
  course_category text not null default 'Core',
  syllabus_units integer not null default 5 check (syllabus_units > 0),
  faculty_id uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.issues (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references public.rooms(id) on delete restrict,
  title text not null, category text not null,
  priority text not null check (priority in ('Low','Medium','High','Critical')),
  priority_rank integer not null check (priority_rank between 1 and 4),
  description text not null, status text not null default 'Open' check (status in ('Open','In Progress','Resolved','Verified')),
  reported_by uuid not null references public.profiles(id) on delete restrict,
  assigned_to uuid references public.profiles(id) on delete set null,
  worker_note text not null default '', faculty_verification text not null default 'Pending',
  created_at timestamptz not null default now(), updated_at timestamptz
);

create table if not exists public.timetable (
  id uuid primary key default gen_random_uuid(),
  day text not null check (day in ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')),
  day_order integer not null check (day_order between 1 and 6),
  start_time time not null, end_time time not null check (end_time > start_time),
  room_id uuid not null references public.rooms(id) on delete restrict,
  section text not null, subject_id uuid not null references public.subjects(id) on delete restrict,
  faculty_id uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.syllabus_progress (
  id uuid primary key default gen_random_uuid(),
  subject_id uuid not null references public.subjects(id) on delete cascade,
  week_number integer not null check (week_number between 1 and 30),
  coverage_percent numeric(5,2) not null check (coverage_percent between 0 and 100),
  topics_covered text not null, updated_by uuid references public.profiles(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique(subject_id, week_number)
);

create index if not exists rooms_category_idx on public.rooms(category);
create index if not exists issues_priority_idx on public.issues(priority_rank desc, created_at desc);
create index if not exists timetable_day_idx on public.timetable(day, start_time);

-- This application accesses Supabase through the protected Flask server using the service-role key.
-- Keep the service-role key only in the host's environment variables; never put it in browser JavaScript.
alter table public.profiles enable row level security;
alter table public.rooms enable row level security;
alter table public.subjects enable row level security;
alter table public.issues enable row level security;
alter table public.timetable enable row level security;
alter table public.syllabus_progress enable row level security;
