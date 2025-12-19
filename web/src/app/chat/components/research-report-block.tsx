// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useCallback, useRef } from "react";

import { LoadingAnimation } from "~/components/ui/loading-animation";
import { Markdown } from "~/components/ui/markdown";
import ReportEditor from "~/components/editor";
import { useReplay } from "~/core/replay";
import { useMessage, useStore } from "~/core/store";
import { cn } from "~/lib/utils";

export function ResearchReportBlock({
  className,
  messageId,
  editing,
}: {
  className?: string;
  researchId: string;
  messageId: string;
  editing: boolean;
}) {
  const message = useMessage(messageId);
  const { isReplay } = useReplay();
  const handleMarkdownChange = useCallback(
    (markdown: string) => {
      if (message) {
        message.content = markdown;
        useStore.setState({
          messages: new Map(useStore.getState().messages).set(
            message.id,
            message,
          ),
        });
      }
    },
    [message],
  );
  const contentRef = useRef<HTMLDivElement>(null);
  const isCompleted = message?.isStreaming === false && message?.content !== "";
  // TODO: scroll to top when completed, but it's not working
  // useEffect(() => {
  //   if (isCompleted && contentRef.current) {
  //     setTimeout(() => {
  //       contentRef
  //         .current!.closest("[data-radix-scroll-area-viewport]")
  //         ?.scrollTo({
  //           top: 0,
  //           behavior: "smooth",
  //         });
  //     }, 500);
  //   }
  // }, [isCompleted]);

  // Debug: log message state
  if (!message) {
    console.warn(`ResearchReportBlock: message ${messageId} not found in store`);
  } else if (!message.content || message.content.trim() === "") {
    console.warn(`ResearchReportBlock: message ${messageId} has empty content`, { isStreaming: message.isStreaming, contentLength: message.content?.length });
  }

  return (
    <div ref={contentRef} className={cn("w-full pt-4 pb-8", className)}>
      {!isReplay && isCompleted && editing ? (
        <ReportEditor
          content={message?.content}
          onMarkdownChange={handleMarkdownChange}
        />
      ) : (
        <>
          {message?.content && message.content.trim() && (
            <Markdown animated checkLinkCredibility>
              {message.content}
            </Markdown>
          )}
          {message?.isStreaming && <LoadingAnimation className="my-12" />}
          {message && (!message.content || message.content.trim() === "") && !message.isStreaming && (
            <div className="text-gray-400 text-center py-8">报告内容为空</div>
          )}
        </>
      )}
    </div>
  );
}
