-- 0002_snippet_provenance.sql — per-slug doc snippet diff anchors.

create table workflow.snippet_provenance (
  snippet_path              text        not null,
  slug                      text        not null,
  head_sha_at_acquisition   text        not null,
  recorded_at               timestamptz not null default now(),
  primary key (snippet_path, slug)
);
