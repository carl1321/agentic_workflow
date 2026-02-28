"use client";

import { useParams, useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "~/components/ui/button";
import { ToolExecutor } from "~/app/chat/components/tool-executor";
import { getToolById } from "~/core/config/tools";
import { useAuthStore } from "~/core/store/auth-store";

/**
 * 独立工具子页面，便于外嵌或分享链接，如 /tools/ppt_generator
 */
export default function ToolPage() {
  const params = useParams();
  const router = useRouter();
  const pathname = usePathname();
  const { token } = useAuthStore();
  const toolId = typeof params.toolId === "string" ? params.toolId : "";
  const tool = getToolById(toolId);

  useEffect(() => {
    if (token === undefined) return;
    if (!token) {
      router.replace(`/login?redirect=${encodeURIComponent(pathname ?? `/tools/${toolId}`)}`);
    }
  }, [token, router, pathname, toolId]);

  const handleBack = () => {
    router.push("/chat?view=toolbox");
  };

  if (token !== undefined && !token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F5F5F5] dark:bg-slate-900">
        <p className="text-slate-500">正在跳转到登录页...</p>
      </div>
    );
  }

  if (!tool) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#F5F5F5] dark:bg-slate-900 p-6">
        <p className="text-slate-600 dark:text-slate-400">未找到该工具</p>
        <Button variant="outline" onClick={handleBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          返回工具箱
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#F5F5F5] dark:bg-slate-900">
      <div className="flex-1 overflow-auto">
        <ToolExecutor
          tool={tool}
          onClose={handleBack}
          onBack={handleBack}
        />
      </div>
    </div>
  );
}
