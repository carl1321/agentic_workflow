// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { MagicWandIcon } from "@radix-ui/react-icons";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, Lightbulb, Paperclip, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

import MessageInput, {
  type MessageInputRef,
} from "~/components/ui/message-input";
import { Tooltip } from "~/components/ui/tooltip";
import { BorderBeam } from "~/components/magicui/border-beam";
import { Button } from "~/components/ui/button";
import { enhancePrompt } from "~/core/api";
import { useConfig } from "~/core/api/hooks";
import type { Option, Resource } from "~/core/messages";
import {
  setEnableDeepThinking,
  useSettingsStore,
  useStore,
} from "~/core/store";
import { cn } from "~/lib/utils";
import type { ModelInfo } from "~/core/config/types";

export function InputBox({
  className,
  responding,
  feedback,
  onSend,
  onCancel,
  onRemoveFeedback,
}: {
  className?: string;
  size?: "large" | "normal";
  responding?: boolean;
  feedback?: { option: Option } | null;
  onSend?: (
    message: string,
    options?: {
      interruptFeedback?: string;
      resources?: Array<Resource>;
    },
  ) => void;
  onCancel?: () => void;
  onRemoveFeedback?: () => void;
}) {
  const t = useTranslations("chat.inputBox");
  const tCommon = useTranslations("common");
  const enableDeepThinking = useSettingsStore(
    (state) => state.general.enableDeepThinking,
  );
  const { config, loading } = useConfig();
  const reportStyle = useSettingsStore((state) => state.general.reportStyle);
  const selectedModel = useStore((state) => state.selectedModel);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<MessageInputRef>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  
  // Check if current model supports thinking
  const currentModelSupportsThinking = (() => {
    if (!config?.models) return false;
    
    // If a model is selected, check if it supports thinking
    if (selectedModel) {
      const allModels: ModelInfo[] = [];
      Object.values(config.models).forEach((modelList) => {
        if (Array.isArray(modelList)) {
          modelList.forEach((model) => {
            if (typeof model === "object" && model !== null && "name" in model) {
              allModels.push(model as ModelInfo);
            }
          });
        }
      });
      const currentModel = allModels.find((m) => m.name === selectedModel);
      return currentModel?.supports_thinking === true;
    }
    
    // If no model selected, check if any model supports thinking
    // (for backward compatibility with REASONING_MODEL)
    const allModels: ModelInfo[] = [];
    Object.values(config.models).forEach((modelList) => {
      if (Array.isArray(modelList)) {
        modelList.forEach((model) => {
          if (typeof model === "object" && model !== null && "name" in model) {
            allModels.push(model as ModelInfo);
          }
        });
      }
    });
    return allModels.some((m) => m.supports_thinking === true);
  })();

  // Enhancement state
  const [isEnhancing, setIsEnhancing] = useState(false);
  const [isEnhanceAnimating, setIsEnhanceAnimating] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState("");
  // 附件（如 POSCAR），发送时拼入用户消息供 VASP 等使用
  const [attachments, setAttachments] = useState<Array<{ name: string; content: string }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSendMessage = useCallback(
    (message: string, resources: Array<Resource>) => {
      if (responding) {
        onCancel?.();
      } else {
        if (message.trim() === "" && attachments.length === 0) {
          return;
        }
        if (onSend) {
          const text = message.trim();
          const withAttachments =
            attachments.length > 0
              ? text +
                "\n\n" +
                attachments
                  .map(
                    (f) =>
                      `[附件: ${f.name}]\n\`\`\`\n${f.content}\n\`\`\``
                  )
                  .join("\n\n")
              : text;
          onSend(withAttachments, {
            interruptFeedback: feedback?.option.value,
            resources,
          });
          onRemoveFeedback?.();
          setAttachments([]);
          setIsEnhanceAnimating(false);
        }
      }
    },
    [responding, onCancel, onSend, feedback, onRemoveFeedback, attachments],
  );

  const handleFileAttach = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        const content = String(reader.result ?? "");
        setAttachments((prev) => [...prev, { name: file.name, content }]);
      };
      reader.readAsText(file, "UTF-8");
      e.target.value = "";
    },
    []
  );

  const handleEnhancePrompt = useCallback(async () => {
    if (currentPrompt.trim() === "" || isEnhancing) {
      return;
    }

    setIsEnhancing(true);
    setIsEnhanceAnimating(true);

    try {
      const enhancedPrompt = await enhancePrompt({
        prompt: currentPrompt,
        report_style: reportStyle.toUpperCase(),
      });

      // Add a small delay for better UX
      await new Promise((resolve) => setTimeout(resolve, 500));

      // Update the input with the enhanced prompt with animation
      if (inputRef.current) {
        inputRef.current.setContent(enhancedPrompt);
        setCurrentPrompt(enhancedPrompt);
      }

      // Keep animation for a bit longer to show the effect
      setTimeout(() => {
        setIsEnhanceAnimating(false);
      }, 1000);
    } catch (error) {
      console.error("Failed to enhance prompt:", error);
      setIsEnhanceAnimating(false);
      // Could add toast notification here
    } finally {
      setIsEnhancing(false);
    }
  }, [currentPrompt, isEnhancing, reportStyle]);

  return (
    <div
      className={cn(
        "bg-card relative flex h-full w-full flex-col rounded-[24px] border",
        className,
      )}
      ref={containerRef}
    >
      <div className="w-full">
        <AnimatePresence>
          {feedback && (
            <motion.div
              ref={feedbackRef}
              className="bg-background border-brand absolute top-0 left-0 mt-2 ml-4 flex items-center justify-center gap-1 rounded-2xl border px-2 py-0.5"
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
            >
              <div className="text-brand flex h-full w-full items-center justify-center text-sm opacity-90">
                {feedback.option.text}
              </div>
              <X
                className="cursor-pointer opacity-60"
                size={16}
                onClick={onRemoveFeedback}
              />
            </motion.div>
          )}
          {isEnhanceAnimating && (
            <motion.div
              className="pointer-events-none absolute inset-0 z-20"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="relative h-full w-full">
                {/* Sparkle effect overlay */}
                <motion.div
                  className="absolute inset-0 rounded-[24px] bg-gradient-to-r from-blue-500/10 via-purple-500/10 to-blue-500/10"
                  animate={{
                    background: [
                      "linear-gradient(45deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1))",
                      "linear-gradient(225deg, rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1))",
                      "linear-gradient(45deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1))",
                    ],
                  }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
                {/* Floating sparkles */}
                {[...Array(6)].map((_, i) => (
                  <motion.div
                    key={i}
                    className="absolute h-2 w-2 rounded-full bg-blue-400"
                    style={{
                      left: `${20 + i * 12}%`,
                      top: `${30 + (i % 2) * 40}%`,
                    }}
                    animate={{
                      y: [-10, -20, -10],
                      opacity: [0, 1, 0],
                      scale: [0.5, 1, 0.5],
                    }}
                    transition={{
                      duration: 1.5,
                      repeat: Infinity,
                      delay: i * 0.2,
                    }}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        {attachments.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 px-4 pt-2">
            {attachments.map((f) => (
              <span
                key={f.name}
                className="inline-flex items-center gap-1 rounded-full border bg-muted/60 px-2 py-1 text-xs"
              >
                <Paperclip className="h-3 w-3 opacity-70" />
                {f.name}
                <button
                  type="button"
                  className="hover:bg-muted rounded p-0.5"
                  onClick={() =>
                    setAttachments((prev) => prev.filter((a) => a.name !== f.name))
                  }
                  aria-label="移除附件"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <MessageInput
          className={cn(
            "h-24 px-4 pt-5",
            feedback && "pt-9",
            isEnhanceAnimating && "transition-all duration-500",
          )}
          ref={inputRef}
          loading={loading}
          config={config}
          onEnter={handleSendMessage}
          onChange={setCurrentPrompt}
        />
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".POSCAR,.poscar,.vasp,.cif,.CIF,.txt,.xml,.XML"
        className="hidden"
        onChange={handleFileAttach}
      />
      <div className="flex items-center px-4 py-2">
        <div className="flex grow gap-2">
          <Tooltip
            className="max-w-60"
            title={
              <div>
                <h3 className="mb-2 font-bold">
                  {t("deepThinkingTooltip.title", {
                    status: enableDeepThinking ? t("on") : t("off"),
                  })}
                </h3>
                <p>
                  {selectedModel && !currentModelSupportsThinking
                    ? t("deepThinkingTooltip.unsupportedModel")
                    : t("deepThinkingTooltip.description", {
                        model: selectedModel || "默认模型",
                      })}
                </p>
              </div>
            }
          >
            <Button
              className={cn(
                "rounded-2xl",
                enableDeepThinking && currentModelSupportsThinking && "!border-brand !text-brand",
                !currentModelSupportsThinking && selectedModel && "opacity-50 cursor-not-allowed",
              )}
              variant="outline"
              disabled={!currentModelSupportsThinking && selectedModel !== null}
              onClick={() => {
                if (currentModelSupportsThinking || !selectedModel) {
                  setEnableDeepThinking(!enableDeepThinking);
                }
              }}
            >
              <Lightbulb /> {t("deepThinking")}
            </Button>
          </Tooltip>
          <Tooltip title="上传附件（如 POSCAR）">
            <Button
              variant="outline"
              size="icon"
              className="h-10 w-10 rounded-2xl"
              onClick={() => fileInputRef.current?.click()}
              disabled={responding}
            >
              <Paperclip className="h-4 w-4" />
            </Button>
          </Tooltip>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Tooltip title={t("enhancePrompt")}>
            <Button
              variant="ghost"
              size="icon"
              className={cn(
                "hover:bg-accent h-10 w-10",
                isEnhancing && "animate-pulse",
              )}
              onClick={handleEnhancePrompt}
              disabled={isEnhancing || currentPrompt.trim() === ""}
            >
              {isEnhancing ? (
                <div className="flex h-10 w-10 items-center justify-center">
                  <div className="bg-foreground h-3 w-3 animate-bounce rounded-full opacity-70" />
                </div>
              ) : (
                <MagicWandIcon className="text-brand" />
              )}
            </Button>
          </Tooltip>
          <Tooltip title={responding ? tCommon("stop") : tCommon("send")}>
            <Button
              variant="outline"
              size="icon"
              className={cn("h-10 w-10 rounded-full")}
              onClick={() => inputRef.current?.submit()}
            >
              {responding ? (
                <div className="flex h-10 w-10 items-center justify-center">
                  <div className="bg-foreground h-4 w-4 rounded-sm opacity-70" />
                </div>
              ) : (
                <ArrowUp />
              )}
            </Button>
          </Tooltip>
        </div>
      </div>
      {isEnhancing && (
        <>
          <BorderBeam
            duration={5}
            size={250}
            className="from-transparent via-red-500 to-transparent"
          />
          <BorderBeam
            duration={5}
            delay={3}
            size={250}
            className="from-transparent via-blue-500 to-transparent"
          />
        </>
      )}
    </div>
  );
}
