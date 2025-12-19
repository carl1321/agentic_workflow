// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { usePathname } from "next/navigation";

import { ThemeProvider } from "~/components/theme-provider";

export function ThemeProviderWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  // Allow theme switching on all pages
  const allowThemeSwitch = true;

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme={"light"}
      enableSystem={allowThemeSwitch}
      forcedTheme={allowThemeSwitch ? undefined : "light"}
      disableTransitionOnChange
    >
      {children}
    </ThemeProvider>
  );
}
