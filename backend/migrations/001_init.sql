-- Aviation Intelligence RAG — initial schema
-- Run once in the Supabase SQL editor (or via psql).
-- NOTE: the vector dimension (384) must match EMBEDDING_DIM / the embedding model.

create extension if not exists vector with schema extensions;  -- Supabase keeps extensions out of public
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.documents (
    id                uuid primary key default gen_random_uuid(),
    title             text        not null,
    description       text,
    original_filename text        not null,
    storage_path      text        not null,
    file_type         text        not null default 'application/pdf',
    file_size         bigint      not null,
    sha256            text        not null unique,
    page_count        integer,
    chunk_count       integer     not null default 0,
    status            text        not null default 'awaiting_upload'
        check (status in ('awaiting_upload', 'queued', 'processing', 'ready', 'failed')),
    error_message     text,
    created_at        timestamptz not null default now(),
    processed_at      timestamptz
);

create index if not exists documents_status_idx on public.documents (status);
create index if not exists documents_created_at_idx on public.documents (created_at desc);

create table if not exists public.chunks (
    id             bigserial primary key,
    document_id    uuid    not null references public.documents (id) on delete cascade,
    chunk_index    integer not null,
    page_start     integer not null,
    page_end       integer not null,
    section        text,
    content        text    not null,
    token_estimate integer not null default 0,
    embedding      extensions.vector(384) not null,
    fts            tsvector generated always as (to_tsvector('english', content)) stored,
    unique (document_id, chunk_index)
);

create index if not exists chunks_document_idx on public.chunks (document_id);
create index if not exists chunks_embedding_hnsw_idx
    on public.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists chunks_fts_idx on public.chunks using gin (fts);

-- Lock the tables down: enable RLS with no policies so the public anon key can read nothing.
-- The backend connects with the database owner role (bypasses RLS).
alter table public.documents enable row level security;
alter table public.chunks enable row level security;
