/**
 * Runs the job-analysis medallion pipeline (`run_pipeline.py`) for a job
 * posting URL and records the target job's summary as versioned data.
 *
 * @module
 */
import { z } from "npm:zod@4";

const GlobalArgsSchema = z.object({
  python: z.string().default(".venv/bin/python").describe(
    "Python interpreter, relative to the repo root or absolute",
  ),
});

type GlobalArgs = z.infer<typeof GlobalArgsSchema>;

const RunArgsSchema = z.object({
  url: z.url().describe("Job posting URL (Ashby, Greenhouse, or any page)"),
  runNotebooks: z.boolean().default(false).describe(
    "Also execute the optional gold analysis notebooks",
  ),
});

type RunArgs = z.infer<typeof RunArgsSchema>;

const SummarySchema = z.object({
  url: z.string(),
  board: z.string(),
  company: z.string(),
  jobId: z.string(),
  title: z.string(),
  department: z.string().nullable(),
  salaryMin: z.number().nullable(),
  salaryMax: z.number().nullable(),
  location: z.string().nullable(),
  ranAt: z.iso.datetime(),
});

// Shape of the last stdout line printed by `run_pipeline.py --json`.
const PipelineOutputSchema = z.object({
  job: z.object({
    board: z.string(),
    company: z.string(),
    job_id: z.string(),
  }),
  summary: z.object({
    title: z.string(),
    department: z.string().nullable(),
    salary_min: z.number().nullable(),
    salary_max: z.number().nullable(),
    location: z.string().nullable(),
  }).nullable(),
});

/** Model definition wrapping the job-analysis pipeline. */
export const model = {
  type: "@kagarmoe/job-pipeline",
  version: "2026.09.21.1",
  globalArguments: GlobalArgsSchema,
  resources: {
    "summary": {
      description: "Silver-layer summary of the target job after a pipeline run",
      schema: SummarySchema,
      lifetime: "infinite",
      garbageCollection: 10,
    },
  },
  methods: {
    run: {
      description:
        "Scrape the job's board, run bronze/silver ETL, and store the target job's summary",
      arguments: RunArgsSchema,
      execute: async (
        args: RunArgs,
        context: {
          globalArgs: GlobalArgs;
          repoDir: string;
          signal: AbortSignal;
          logger: { info: (msg: string) => void };
          writeResource: (
            specName: string,
            name: string,
            data: Record<string, unknown>,
          ) => Promise<{ name: string }>;
        },
      ): Promise<{ dataHandles: { name: string }[] }> => {
        const cmdArgs = ["run_pipeline.py", args.url, "--json"];
        if (args.runNotebooks) cmdArgs.push("--run-notebooks");

        context.logger.info(`Running pipeline for ${args.url}`);
        const child = new Deno.Command(context.globalArgs.python, {
          args: cmdArgs,
          cwd: context.repoDir,
          signal: context.signal,
          stdout: "piped",
          stderr: "piped",
        }).spawn();

        // Wayback can take many minutes: stream the pipeline's log as it
        // arrives instead of going silent, keeping a tail for error reports.
        let stderrTail = "";
        const pumpLogs = async (): Promise<void> => {
          const chunks = child.stderr.pipeThrough(new TextDecoderStream());
          for await (const chunk of chunks) {
            stderrTail = (stderrTail + chunk).slice(-2000);
            context.logger.info(chunk.trimEnd());
          }
        };
        const [{ code }, stdoutText] = await Promise.all([
          child.status,
          new Response(child.stdout).text(),
          pumpLogs(),
        ]);

        if (code !== 0) {
          throw new Error(`run_pipeline.py exited ${code}:\n${stderrTail}`);
        }

        // Scrapers may print to stdout; the contract is only the last line.
        const lastLine = stdoutText.trim().split("\n").at(-1) ?? "";
        const { job, summary } = PipelineOutputSchema.parse(
          JSON.parse(lastLine),
        );
        if (!summary) {
          throw new Error(
            `Pipeline ran but job ${job.job_id} was not found in silver (${job.board}/${job.company})`,
          );
        }

        const name = `${job.board}-${job.company}-${job.job_id}`
          .replace(/[^a-zA-Z0-9_-]/g, "-");
        const handle = await context.writeResource("summary", name, {
          url: args.url,
          board: job.board,
          company: job.company,
          jobId: job.job_id,
          title: summary.title,
          department: summary.department,
          salaryMin: summary.salary_min,
          salaryMax: summary.salary_max,
          location: summary.location,
          ranAt: new Date().toISOString(),
        });
        return { dataHandles: [handle] };
      },
    },
  },
};
