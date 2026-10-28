import { NextResponse } from "next/server";
import fs from "fs";

export const dynamic = "force-dynamic";

export async function GET() {
  const userConfigPath = process.env.USER_CONFIG_PATH;

  let keyFromFile = "";
  let googleKeyFromFile = "";
  let customKeyFromFile = "";
  if (userConfigPath && fs.existsSync(userConfigPath)) {
    try {
      const raw = fs.readFileSync(userConfigPath, "utf-8");
      const cfg = JSON.parse(raw || "{}");
      keyFromFile = cfg?.OPENAI_API_KEY || "";
      googleKeyFromFile = cfg?.GOOGLE_API_KEY || "";
      customKeyFromFile = cfg?.CUSTOM_LLM_API_KEY || "";
    } catch { }
  }

  const keyFromEnv = process.env.OPENAI_API_KEY || "";
  const googleKeyFromEnv = process.env.GOOGLE_API_KEY || "";
  const customKeyFromEnv = process.env.CUSTOM_LLM_API_KEY || "";

  const hasKey = [
    keyFromFile,
    googleKeyFromFile,
    customKeyFromFile,
    keyFromEnv,
    googleKeyFromEnv,
    customKeyFromEnv,
  ].some((key) => Boolean(String(key || "").trim()));

  return NextResponse.json({ hasKey });
} 
