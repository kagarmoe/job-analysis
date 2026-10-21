/**
 * Runs graphify's headless pipeline on the repo: incremental extraction
 * (AST + LLM semantic pass on changed docs) and community labeling, and
 * records the resulting graph's size as versioned data.
 *
 * @module
 */
import { z } from "npm:zod@4";

const GlobalArgsSchema = z.object({
  graphify: z.string().default("graphify").describe(
    "graphify executable, on PATH or absolute",
  ),
  backend: z.string().default("gemini").describe(
    "graphify LLM backend (gemini, claude-cli, claude, ...)",
  ),
  apiKey: z.string().default("").meta({ sensitive: true }).describe(
    "API key for the backend; not needed for claude-cli",
  ),
});

type GlobalArgs = z.infer<typeof GlobalArgsSchema>;

const ExtractArgsSchema = z.object({
  deep: z.boolean().default(false).describe(
    "Aggressive INFERRED-edge semantic extraction (--mode deep)",
  ),
  tokenBudget: z.number().int().positive().default(60000).describe(
    "Per-chunk token cap for the semantic pass (--token-budget); lower it when the model omits files from a large chunk",
  ),
});

type ExtractArgs = z.infer<typeof ExtractArgsSchema>;

const SummarySchema = z.object({
  nodes: z.number(),
  edges: z.number(),
  communities: z.number(),
  inferredEdges: z.number(),
  ambiguousEdges: z.number(),
  inputTokens: z.number(),
  outputTokens: z.number(),
  builtAtCommit: z.string().nullable(),
  ranAt: z.iso.datetime(),
});

// The parts of graphify-out/graph.json and .graphify_analysis.json we read.
const GraphSchema = z.object({
  nodes: z.array(z.object({ community: z.number().nullish() })),
  links: z.array(z.object({ confidence: z.string().nullish() })),
  built_at_commit: z.string().nullish(),
});
const AnalysisSchema = z.object({
  tokens: z.object({ input: z.number(), output: z.number() }),
});

type Context = {
  globalArgs: GlobalArgs;
  repoDir: string;
  signal: AbortSignal;
  logger: { info: (msg: string) => void };
  writeResource: (
    specName: string,
    name: string,
    data: Record<string, unknown>,
  ) => Promise<{ name: string }>;
};

// graphify reads the key from these env vars; it errors only if LLM work is pending.
const KEY_ENV: Record<string, string> = {
  gemini: "GEMINI_API_KEY",
  claude: "ANTHROPIC_API_KEY",
};

async function runGraphify(args: string[], context: Context): Promise<void> {
  const { graphify, backend, apiKey } = context.globalArgs;
  const env: Record<string, string> = {};
  if (apiKey && KEY_ENV[backend]) env[KEY_ENV[backend]] = apiKey;

  context.logger.info(`${graphify} ${args.join(" ")}`);
  const child = new Deno.Command(graphify, {
    args,
    cwd: context.repoDir,
    env,
    signal: context.signal,
    stdout: "piped",
    stderr: "piped",
  }).spawn();

  // Semantic extraction can run for minutes: stream output, keep a tail for errors.
  let tail = "";
  const pump = async (stream: ReadableStream<Uint8Array>): Promise<void> => {
    for await (const chunk of stream.pipeThrough(new TextDecoderStream())) {
      tail = (tail + chunk).slice(-2000);
      context.logger.info(chunk.trimEnd());
    }
  };
  const [{ code }] = await Promise.all([
    child.status,
    pump(child.stdout),
    pump(child.stderr),
  ]);
  if (code !== 0) {
    throw new Error(`graphify ${args[0]} exited ${code}:\n${tail}`);
  }
}

/** Model definition wrapping the graphify CLI. */
export const model = {
  type: "@kagarmoe/graphify",
  version: "2026.10.20.1",
  globalArguments: GlobalArgsSchema,
  resources: {
    "summary": {
      description: "Size, confidence mix and token cost of the latest graph",
      schema: SummarySchema,
      lifetime: "infinite",
      garbageCollection: 20,
    },
  },
  methods: {
    extract: {
      description:
        "Incrementally extract the repo into graphify-out/graph.json (AST + LLM semantic pass)",
      arguments: ExtractArgsSchema,
      execute: async (
        args: ExtractArgs,
        context: Context,
      ): Promise<{ dataHandles: { name: string }[] }> => {
        const cmd = [
          "extract", ".", "--backend", context.globalArgs.backend,
          "--token-budget", String(args.tokenBudget),
        ];
        if (args.deep) cmd.push("--mode", "deep");
        await runGraphify(cmd, context);

        const out = `${context.repoDir}/graphify-out`;
        const graph = GraphSchema.parse(
          JSON.parse(await Deno.readTextFile(`${out}/graph.json`)),
        );
        const { tokens } = AnalysisSchema.parse(
          JSON.parse(await Deno.readTextFile(`${out}/.graphify_analysis.json`)),
        );
        const countConfidence = (c: string) =>
          graph.links.filter((l) => l.confidence === c).length;

        const handle = await context.writeResource("summary", "graph", {
          nodes: graph.nodes.length,
          edges: graph.links.length,
          communities: new Set(graph.nodes.map((n) => n.community)).size,
          inferredEdges: countConfidence("INFERRED"),
          ambiguousEdges: countConfidence("AMBIGUOUS"),
          inputTokens: tokens.input,
          outputTokens: tokens.output,
          builtAtCommit: graph.built_at_commit ?? null,
          ranAt: new Date().toISOString(),
        });
        return { dataHandles: [handle] };
      },
    },
    label: {
      description:
        "Recluster, name communities with the LLM, and write GRAPH_REPORT.md + graph.html",
      arguments: z.object({}),
      execute: async (
        _args: Record<string, never>,
        context: Context,
      ): Promise<{ dataHandles: { name: string }[] }> => {
        // `label`, not `cluster-only`: the latter reuses .graphify_labels.json,
        // leaving new communities as "Community N" after re-extraction.
        await runGraphify(
          ["label", ".", `--backend=${context.globalArgs.backend}`],
          context,
        );
        return { dataHandles: [] };
      },
    },
  },
};
