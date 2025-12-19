// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { useTranslations } from "next-intl";

import { cn } from "~/lib/utils";

import { Welcome } from "./welcome";

export function ConversationStarter({
  className,
  onSend,
}: {
  className?: string;
  onSend?: (message: string) => void;
}) {
  const t = useTranslations("chat");
  const questions = t.raw("conversationStarters") as string[];

  const tWelcome = useTranslations("chat.welcome");

  return (
    <div className={cn("flex flex-col items-center w-full space-y-8", className)}>
      {/* 欢迎区域 */}
      <div className="text-center w-full">
        <h1 className="text-4xl font-semibold mb-3">
          {tWelcome("greeting")}
        </h1>
        <p className="text-base text-slate-600 dark:text-slate-400 leading-relaxed">
          {tWelcome("description")}
        </p>
      </div>
      
      {/* 示例卡片 */}
      <div className="w-full grid grid-cols-2 gap-3">
        {questions.map((question, index) => (
          <motion.div
            key={`${index}-${question}`}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{
              duration: 0.2,
              delay: index * 0.1 + 0.5,
              ease: "easeOut",
            }}
          >
            <div
              className="bg-white dark:bg-slate-800 cursor-pointer rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-4 min-h-[80px] transition-all duration-200 hover:shadow-md hover:border-blue-500 dark:hover:border-blue-500 hover:-translate-y-1 text-sm text-slate-700 dark:text-slate-300 flex items-center"
              onClick={() => {
                onSend?.(question);
              }}
            >
              {question}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
