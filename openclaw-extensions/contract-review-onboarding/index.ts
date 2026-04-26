type ContractReviewOnboardingConfig = {
  mode?: "local" | "cloud";
  contractReviewHome?: string;
  sampleContractPath?: string;
};

const SAMPLE_CONTRACT_NAME =
  "华为-中大智算集群可靠性测评技术合作协议-脱敏版.docx";

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function buildLocalSamplePath(config: ContractReviewOnboardingConfig): string {
  const configuredSample = cleanText(config.sampleContractPath);
  if (configuredSample) return configuredSample;

  const home = cleanText(config.contractReviewHome).replace(/[\\\/]+$/, "");
  if (!home) return "<合同文件完整路径>";
  return `${home}\\samples\\${SAMPLE_CONTRACT_NAME}`;
}

function buildPrompt(config: ContractReviewOnboardingConfig): string {
  const mode = config.mode === "cloud" ? "cloud" : "local";
  const localSample = buildLocalSamplePath(config);

  const shared = `
# Contract Formal Review Onboarding

You are configured for Sun Yat-sen University horizontal contract formal review.

When the user only greets you, asks what you can do, or opens a new dashboard chat without a concrete task, reply in Chinese with a short administrative-user greeting. The greeting must explain the simplest contract review prompt and must not mention Python, shell commands, JSON, YAML, schemas, rule ids, or implementation details.

When the user provides a contract file path, attachment, or file link and asks for contract review, do not stop at explaining usage. Use the installed "contract-formal-review-flow" skill and complete the review. Normal final answers must be written for administrative teachers: clear conclusion, tables of issues, linked clauses/evidence, suggested handling, enterprise verification status, IP focus, and output locations when available.

Default review prompt to teach users:
请帮我审核这个合同，<合同文件完整路径或上传文件>

Local-only review prompt to teach users when they do not want enterprise lookup:
请帮我审核这个合同，但不要打开企查查，只做本地合同审核：<合同文件完整路径或上传文件>

Default behavior: attempt Qichacha verification for Party A when the runtime supports it. If Qichacha login, captcha, access limits, missing fields, or network restrictions prevent usable verification, continue the ordinary contract review and clearly state that enterprise verification still needs a screenshot or manual verification record.

Never bypass login, captcha, WAF, paywalls, robots restrictions, or access controls.
`.trim();

  if (mode === "cloud") {
    return `${shared}

Cloud ArkClaw wording for greeting:
我可以帮你做横向合同形式化审核。最简单的用法是：上传合同后直接说“请帮我审核这个合同”。如果是文件链接或云端路径，就说“请帮我审核这个合同，<文件链接或云端路径>”。默认会尝试核验甲方企业信息；核验受限时也会先完成合同审核，并把需要补充的企业材料列清楚。`;
  }

  return `${shared}

Local OpenClaw wording for greeting:
我可以帮你做横向合同形式化审核。最简单的用法是：请帮我审核这个合同，<合同文件完整路径>。例如：请帮我审核这个合同，${localSample}。默认会尝试复用企查查登录状态核验甲方；登录失效时会弹二维码；核验受限时也会先完成合同审核，并把需要补充的企业材料列清楚。`;
}

const plugin = {
  id: "contract-review-onboarding",
  name: "Contract Review Onboarding Prompt",
  description: "Adds contract review usage guidance to the global OpenClaw prompt.",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      mode: { type: "string", enum: ["local", "cloud"] },
      contractReviewHome: { type: "string" },
      sampleContractPath: { type: "string" },
    },
  },
  register(api: { pluginConfig?: unknown; on: Function }) {
    const config = (api.pluginConfig ?? {}) as ContractReviewOnboardingConfig;
    api.on(
      "before_prompt_build",
      () => ({
        appendSystemContext: buildPrompt(config),
      }),
      { priority: 20 },
    );
  },
};

export default plugin;
