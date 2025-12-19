// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { ChevronRight, Atom, Zap, Database } from "lucide-react";
import Link from "next/link";

import { AuroraText } from "~/components/magicui/aurora-text";
import { FlickeringGrid } from "~/components/magicui/flickering-grid";
import { Button } from "~/components/ui/button";

export function Jumbotron() {
  return (
    <section className="relative flex h-[95vh] w-full flex-col items-center justify-center overflow-hidden pb-15">
      {/* 深色科技感渐变背景 - 材料科学主题 */}
      <div className="absolute inset-0 bg-gradient-to-br from-slate-950 via-blue-950 via-indigo-950 to-cyan-950" />
      
      {/* 动态网格背景 - 模拟分子结构 */}
      <FlickeringGrid
        id="hero-bg-grid"
        className="absolute inset-0 z-0 opacity-25"
        squareSize={4}
        gridGap={4}
        color="#3b82f6"
        maxOpacity={0.15}
        flickerChance={0.12}
      />
      
      {/* 科技感光效粒子层 - 模拟原子结构 */}
      <div className="absolute inset-0 z-0">
        {/* 主光球 - 中心 */}
        <div className="absolute top-1/2 left-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-500/15 blur-3xl animate-pulse" />
        {/* 左上光球 */}
        <div className="absolute top-1/4 left-1/4 h-96 w-96 rounded-full bg-blue-500/20 blur-3xl animate-pulse" style={{ animationDelay: '0.5s' }} />
        {/* 右下光球 */}
        <div className="absolute bottom-1/4 right-1/4 h-96 w-96 rounded-full bg-indigo-500/20 blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
        {/* 右上光球 */}
        <div className="absolute top-1/3 right-1/3 h-64 w-64 rounded-full bg-cyan-400/15 blur-2xl animate-pulse" style={{ animationDelay: '1.5s' }} />
      </div>
      
      {/* 分子结构装饰网格 */}
      <div className="absolute inset-0 z-0 opacity-8">
        <div className="absolute inset-0" style={{
          backgroundImage: `
            radial-gradient(circle at 2px 2px, rgba(59, 130, 246, 0.15) 1px, transparent 0),
            linear-gradient(rgba(59, 130, 246, 0.08) 1px, transparent 1px),
            linear-gradient(90deg, rgba(59, 130, 246, 0.08) 1px, transparent 1px)
          `,
          backgroundSize: '40px 40px, 60px 60px, 60px 60px',
        }} />
      </div>
      
      {/* 主要内容 */}
      <div className="relative z-10 flex flex-col items-center justify-center gap-10 px-4 max-w-6xl mx-auto">
        {/* 顶部标签 */}
        <div className="flex items-center gap-3 mb-2">
          <div className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-blue-500/10 border border-blue-400/20 backdrop-blur-sm">
            <Atom className="h-5 w-5 text-cyan-400" />
            <span className="text-sm font-semibold text-cyan-300 uppercase tracking-widest">
              Material Science AI
            </span>
          </div>
        </div>
        
        {/* 主标题 */}
        <h1 className="text-center text-5xl font-extrabold md:text-7xl lg:text-8xl leading-tight">
          <span className="block bg-gradient-to-r from-white via-cyan-200 via-blue-200 to-indigo-200 bg-clip-text text-transparent mb-3">
            AI 研究代理
          </span>
          <AuroraText className="block text-3xl md:text-5xl lg:text-6xl font-light">
            赋能材料科学
          </AuroraText>
        </h1>
        
        {/* 副标题描述 */}
        <p className="max-w-4xl text-center text-lg md:text-2xl text-slate-300 leading-relaxed font-light">
          您的智能材料研究助手
        </p>
        
        {/* 功能亮点 */}
        <div className="flex flex-wrap justify-center gap-6 mt-4 mb-6">
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/30 backdrop-blur-sm border border-slate-700/50">
            <Zap className="h-4 w-4 text-cyan-400" />
            <span className="text-sm text-slate-300">智能材料设计</span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/30 backdrop-blur-sm border border-slate-700/50">
            <Database className="h-4 w-4 text-blue-400" />
            <span className="text-sm text-slate-300">数据分析洞察</span>
          </div>
          <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800/30 backdrop-blur-sm border border-slate-700/50">
            <Atom className="h-4 w-4 text-indigo-400" />
            <span className="text-sm text-slate-300">分子结构探索</span>
          </div>
        </div>
        
        {/* 详细描述 */}
        <p className="max-w-3xl text-center text-base md:text-lg text-slate-400 leading-relaxed mt-2">
          集成搜索引擎、网络爬虫、Python 计算引擎和 MCP 服务等强大工具，
          <br className="hidden md:block" />
          为您提供即时洞察、深度分析和专业研究支持，加速材料科学创新突破
        </p>
        
        {/* 单一行动按钮 */}
        <div className="mt-8">
          <Button 
            className="group text-lg px-10 py-7 bg-gradient-to-r from-cyan-600 via-blue-600 to-indigo-600 hover:from-cyan-700 hover:via-blue-700 hover:to-indigo-700 text-white border-0 shadow-2xl shadow-cyan-500/30 hover:shadow-cyan-500/50 transition-all duration-300 rounded-xl font-semibold" 
            size="lg" 
            asChild
          >
            <Link href="/chat" className="flex items-center gap-2">
              开始使用
              <ChevronRight className="ml-1 h-5 w-5 group-hover:translate-x-1 transition-transform" />
            </Link>
          </Button>
        </div>
      </div>
      
      {/* 底部装饰 */}
      <div className="absolute bottom-12 flex flex-col items-center gap-2 text-xs text-slate-500 z-10">
        <div className="flex items-center gap-2">
          <div className="h-px w-12 bg-gradient-to-r from-transparent to-cyan-500/50" />
          <span className="text-cyan-400/60">Powered by Advanced AI</span>
          <div className="h-px w-12 bg-gradient-to-l from-transparent to-cyan-500/50" />
        </div>
      </div>
    </section>
  );
}

