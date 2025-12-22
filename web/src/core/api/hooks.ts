// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from "react";

import { env } from "~/env";

import type { AIResearchAgentConfig } from "../config";
import { useReplay } from "../replay";

import { fetchReplayTitle } from "./chat";
import { resolveServiceURL } from "./resolve-service-url";

export function useReplayMetadata() {
  const { isReplay } = useReplay();
  const [title, setTitle] = useState<string | null>(null);
  const isLoading = useRef(false);
  const [error, setError] = useState<boolean>(false);
  useEffect(() => {
    if (!isReplay) {
      return;
    }
    if (title || isLoading.current) {
      return;
    }
    isLoading.current = true;
    fetchReplayTitle()
      .then((title) => {
        setError(false);
        setTitle(title ?? null);
        if (title) {
          document.title = `${title} - AgenticWorkflow`;
        }
      })
      .catch(() => {
        setError(true);
        setTitle("Error: the replay is not available.");
        document.title = "AgenticWorkflow";
      })
      .finally(() => {
        isLoading.current = false;
      });
  }, [isLoading, isReplay, title]);
  return { title, isLoading, hasError: error };
}

export function useConfig(): {
  config: AIResearchAgentConfig | null;
  loading: boolean;
} {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<AIResearchAgentConfig | null>(null);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY) {
      setLoading(false);
      return;
    }
    // 使用 apiRequest 以便统一处理 401 错误
    import("./api-client").then(({ apiRequest }) => {
      apiRequest<AIResearchAgentConfig>("config", { method: "GET" })
        .then((config) => {
          console.log("[useConfig] Config loaded successfully:", config);
          setConfig(config);
          setLoading(false);
        })
        .catch((err) => {
          console.error("[useConfig] Failed to fetch config:", err);
          console.error("[useConfig] Make sure the backend server is running on the correct port");
          setConfig(null);
          setLoading(false);
        });
    });
  }, []);

  return { config, loading };
}
