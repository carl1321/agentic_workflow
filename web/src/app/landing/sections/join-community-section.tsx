// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { ArrowRight, Users } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { AuroraText } from "~/components/magicui/aurora-text";
import { Button } from "~/components/ui/button";

import { SectionHeader } from "../components/section-header";

export function JoinCommunitySection() {
  const t = useTranslations("landing.joinCommunity");
  return (
    <section className="flex w-full flex-col items-center justify-center pb-12">
      <SectionHeader
        anchor="join-community"
        title={
          <AuroraText colors={["#6366f1", "#8b5cf6", "#a855f7"]}>
            {t("title")}
          </AuroraText>
        }
        description={t("description")}
      />
      <Button 
        className="text-xl px-8 py-6 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white border-0 shadow-lg shadow-indigo-500/50" 
        size="lg" 
        asChild
      >
        <Link href="/chat">
          <Users className="mr-2" />
          开始使用
          <ArrowRight className="ml-2" />
        </Link>
      </Button>
    </section>
  );
}
