"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { LoginRequest, LoginResponse, UserInfo } from "../api/auth";
import { fetchCurrentUser, login as apiLogin } from "../api/auth";

export interface AuthState {
  user: UserInfo | null;
  token: string | null;
  loading: boolean;
  error: string | null;

  login: (payload: LoginRequest) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      loading: false,
      error: null,

      async login(payload: LoginRequest) {
        try {
          set({ loading: true, error: null });
          const res: LoginResponse = await apiLogin(payload);
          set({
            user: res.user,
            token: res.access_token,
            loading: false,
            error: null,
          });
        } catch (e: any) {
          const msg =
            e instanceof Error ? e.message : "登录失败，请稍后重试";
          set({ loading: false, error: msg, user: null, token: null });
          throw e;
        }
      },

      logout() {
        set({ user: null, token: null, error: null });
      },

      async refreshUser() {
        const token = get().token;
        if (!token) return;
        try {
          set({ loading: true, error: null });
          const user = await fetchCurrentUser(token);
          set({ user, loading: false, error: null });
        } catch (e: any) {
          const msg =
            e instanceof Error ? e.message : "刷新用户信息失败，请重新登录";
          console.error(e);
          set({ loading: false, error: msg, user: null, token: null });
        }
      },
    }),
    {
      name: "auth-store",
      partialize: (state) => ({
        token: state.token,
        user: state.user,
      }),
    },
  ),
);


