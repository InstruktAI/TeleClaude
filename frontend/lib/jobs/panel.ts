import type { JobInfo } from "@/lib/api/types";

export interface JobsPanelRow {
  name: string;
  type: JobInfo["type"];
  scheduleLabel: string;
  lastRun: string | null;
  status: string;
}

export interface JobsSections {
  scheduled: JobsPanelRow[];
  oneShot: JobsPanelRow[];
}

export interface JobTriggerRequest {
  method: "POST";
  path: string;
}

function toRow(job: JobInfo): JobsPanelRow {
  return {
    name: job.name,
    type: job.type,
    scheduleLabel: job.schedule ?? "one-shot",
    lastRun: job.last_run,
    status: job.status,
  };
}

export function buildJobsSections(jobs: readonly JobInfo[]): JobsSections {
  return jobs.reduce<JobsSections>(
    (sections, job) => {
      if (job.schedule) {
        sections.scheduled.push(toRow(job));
      } else {
        sections.oneShot.push(toRow(job));
      }
      return sections;
    },
    { scheduled: [], oneShot: [] },
  );
}

export function buildJobTriggerRequest(name: string): JobTriggerRequest {
  return {
    method: "POST",
    path: `/api/jobs/${encodeURIComponent(name)}/run`,
  };
}
