// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import en from "../messages/en.json";
import zh from "../messages/zh.json";

const locales: Array<string> = ["zh", "en"];
const messagesMap: Record<string, typeof zh> = { zh, en };

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get("NEXT_LOCALE")?.value;

  const locale =
    cookieLocale && locales.includes(cookieLocale) ? cookieLocale : "zh";

  const messages = messagesMap[locale] ?? zh;

  return {
    messages,
    locale,
  };
});
