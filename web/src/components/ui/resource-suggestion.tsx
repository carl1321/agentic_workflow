// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { MentionOptions } from "@tiptap/extension-mention";
import { ReactRenderer } from "@tiptap/react";
import {
  ResourceMentions,
  type ResourceMentionsProps,
} from "./resource-mentions";
import type { Instance, Props } from "tippy.js";
import tippy from "tippy.js";
import { resolveServiceURL } from "~/core/api/resolve-service-url";
import type { Resource } from "~/core/messages";

export const resourceSuggestion: MentionOptions["suggestion"] = {
  items: ({ query }) => {
    // 走统一的 /api/rag/resources 路径
    return fetch(resolveServiceURL(`rag/resources?query=${encodeURIComponent(query)}`), {
      method: "GET",
    })
      .then((res) => res.json())
      .then((res) => {
        return res.resources as Array<Resource>;
      })
      .catch((err) => {
        return [];
      });
  },

  render: () => {
    let reactRenderer: ReactRenderer<
      { onKeyDown: (args: { event: KeyboardEvent }) => boolean },
      ResourceMentionsProps
    >;
    let popup: Instance<Props>[] | null = null;
    let currentProps: any = null;

    // 获取准确的坐标
    const getClientRect = (): DOMRect => {
      // 不使用 TipTap 的 clientRect，因为它返回的是 (0,0)
      // 直接使用编辑器坐标计算
      
      // 使用编辑器坐标（通过 DOM 元素获取准确的视口坐标）
      if (currentProps?.editor?.view) {
        const editorView = currentProps.editor.view;
        const selection = editorView.state.selection;
        const { from } = selection;
        
        try {
          // 方法1: 使用 domAtPos 和 Range 获取精确坐标
          const dom = editorView.domAtPos(from);
          
          if (dom.node && dom.node.nodeType === Node.TEXT_NODE) {
            // 对于文本节点，创建 Range 来获取光标位置
            const textNode = dom.node;
            const offset = Math.min(dom.offset, textNode.textContent?.length || 0);
            
            const range = document.createRange();
            range.setStart(textNode, offset);
            range.setEnd(textNode, offset);
            
            const rect = range.getBoundingClientRect();
            
            // Range.getBoundingClientRect() 返回的是视口坐标，应该总是有效的
            if (rect && (rect.top !== 0 || rect.left !== 0 || rect.width > 0 || rect.height > 0)) {
              // 确保有最小宽度和高度，以便 tippy 可以正确定位
              return {
                top: rect.top,
                left: rect.left,
                right: rect.right || rect.left + 1,
                bottom: rect.bottom || rect.top + 1,
                width: Math.max(rect.width, 1),
                height: Math.max(rect.height, 1),
                x: rect.left,
                y: rect.top,
                toJSON: () => ({}),
              } as DOMRect;
            }
          }
        } catch (e) {
          // 忽略错误，继续使用回退方案
        }
        
        // 方法2: 使用 coordsAtPos（返回视口坐标）
        const coords = editorView.coordsAtPos(from);
        
        // coordsAtPos 返回的坐标应该是视口坐标，但可能在某些情况下不准确
        // 如果坐标是 (0,0)，说明可能有问题，尝试使用编辑器 DOM 元素的位置
        if (coords.top === 0 && coords.left === 0) {
          // 尝试获取编辑器容器的位置
          const editorDOM = editorView.dom;
          const editorRect = editorDOM.getBoundingClientRect();
          
          // 如果编辑器容器有位置，使用它作为参考
          if (editorRect.top > 0 || editorRect.left > 0) {
            // 使用编辑器容器的底部作为弹出框位置
            return {
              top: editorRect.bottom - 20, // 稍微向上偏移
              left: editorRect.left + 10, // 稍微向右偏移
              right: editorRect.left + 11,
              bottom: editorRect.bottom - 19,
              width: 1,
              height: 1,
              x: editorRect.left + 10,
              y: editorRect.bottom - 20,
              toJSON: () => ({}),
            } as DOMRect;
          }
        }
        
        return {
          top: coords.top,
          left: coords.left,
          right: coords.right || coords.left + 1,
          bottom: coords.bottom || coords.top + 1,
          width: 1,
          height: 1,
          x: coords.left,
          y: coords.top,
          toJSON: () => ({}),
        } as DOMRect;
      }
      
      // 最后的回退方案
      return {
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: 0,
        height: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      } as DOMRect;
    };

    return {
      onStart: (props) => {
        currentProps = props;
        reactRenderer = new ReactRenderer(ResourceMentions, {
          props,
          editor: props.editor,
        });

        // 创建更新位置的函数
        const updatePosition = () => {
          if (popup?.[0] && !popup[0].state.isDestroyed) {
            popup[0].setProps({
              getReferenceClientRect: getClientRect,
            });
          }
        };

        // 监听滚动事件（使用 requestAnimationFrame 优化性能）
        const handleScroll = () => {
          requestAnimationFrame(updatePosition);
        };

        // 监听窗口大小变化
        const handleResize = () => {
          requestAnimationFrame(updatePosition);
        };

        // 添加事件监听器
        window.addEventListener("scroll", handleScroll, { passive: true, capture: true });
        window.addEventListener("resize", handleResize, { passive: true });

        popup = tippy("body", {
          getReferenceClientRect: getClientRect,
          appendTo: () => document.body,
          content: reactRenderer.element,
          showOnCreate: true,
          interactive: true,
          trigger: "manual",
          placement: "top-start",
          offset: [0, 8], // 添加一点偏移，避免紧贴输入框
        });

        // 存储清理函数（在 popup 创建后）
        const cleanup = () => {
          window.removeEventListener("scroll", handleScroll, { capture: true });
          window.removeEventListener("resize", handleResize);
        };
        if (popup?.[0]) {
          (popup[0] as any)._cleanup = cleanup;
        }

        // 在创建后立即更新一次位置
        requestAnimationFrame(updatePosition);
      },

      onUpdate(props) {
        currentProps = props;
        if (reactRenderer) {
          reactRenderer.updateProps(props);
        }

        if (popup?.[0] && !popup[0].state.isDestroyed) {
          // 使用 requestAnimationFrame 确保在下一帧更新位置
          requestAnimationFrame(() => {
            popup?.[0]?.setProps({
              getReferenceClientRect: getClientRect,
            });
          });
        }
      },

      onKeyDown(props) {
        if (props.event.key === "Escape") {
          popup?.[0]?.hide();

          return true;
        }

        return reactRenderer.ref?.onKeyDown(props) ?? false;
      },

      onExit() {
        // 清理事件监听器
        if (popup?.[0] && (popup[0] as any)._cleanup) {
          (popup[0] as any)._cleanup();
        }

        currentProps = null;

        if (popup?.[0]) {
          popup[0].destroy();
        }
        reactRenderer.destroy();
      },
    };
  },
};
