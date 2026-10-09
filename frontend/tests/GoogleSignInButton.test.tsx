import { webcrypto } from "node:crypto";
import type { ComponentProps, ReactNode } from "react";
import type { GoogleLogin } from "@react-oauth/google";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { GoogleSignInButton } from "@/components/auth/GoogleSignInButton";

const auth = vi.hoisted(() => ({ signInWithIdToken: vi.fn(), createClient: vi.fn() }));
let googleProps: ComponentProps<typeof GoogleLogin>;

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => { auth.createClient(); return { auth: { signInWithIdToken: auth.signInWithIdToken } }; },
}));
vi.mock("@react-oauth/google", () => ({
  GoogleOAuthProvider: ({ children }: { children: ReactNode }) => children,
  useGoogleOAuth: () => ({ scriptLoadedSuccessfully: true }),
  GoogleLogin: (props: ComponentProps<typeof GoogleLogin>) => {
    googleProps = props;
    return <button type="button" onClick={() => props.onSuccess({ credential: "fixture-token" })}>Tiếp tục với Google</button>;
  },
}));

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com");
  vi.stubGlobal("crypto", webcrypto);
  auth.signInWithIdToken.mockReset();
  auth.createClient.mockClear();
});

it("leaves a clear email-login path when the Google Client ID is absent", () => {
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_CLIENT_ID", "");
  render(<GoogleSignInButton />);
  expect(screen.getByRole("status")).toHaveTextContent("Bạn có thể đăng nhập bằng email");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(auth.createClient).not.toHaveBeenCalled();
});

it("does not exchange a missing Google credential", async () => {
  render(<GoogleSignInButton />);
  await screen.findByRole("button", { name: "Tiếp tục với Google" });
  act(() => { googleProps.onSuccess({}); });
  expect(screen.getByRole("alert")).toHaveTextContent("Google chưa trả về thông tin đăng nhập");
  expect(auth.signInWithIdToken).not.toHaveBeenCalled();
});

it("requires a session and deduplicates credentials while exchanging them", async () => {
  let resolve!: (value: { data: { session: null }; error: null }) => void;
  auth.signInWithIdToken.mockReturnValue(new Promise((done) => { resolve = done; }));
  render(<GoogleSignInButton />);
  const button = await screen.findByRole("button", { name: "Tiếp tục với Google" });
  const callback = googleProps.onSuccess;
  fireEvent.click(button);
  act(() => { callback({ credential: "duplicate-token" }); });
  expect(auth.signInWithIdToken).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status")).toHaveTextContent("Đang đăng nhập");
  await act(async () => { resolve({ data: { session: null }, error: null }); });
  expect(screen.getByRole("alert")).toHaveTextContent("Không thể đăng nhập bằng Google");
  await screen.findByRole("button", { name: "Tiếp tục với Google" });
});

it("recovers from a rejected exchange and makes the button available again", async () => {
  auth.signInWithIdToken.mockRejectedValue(new Error("fixture network failure"));
  render(<GoogleSignInButton />);
  fireEvent.click(await screen.findByRole("button", { name: "Tiếp tục với Google" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Không thể kết nối dịch vụ đăng nhập"));
  await screen.findByRole("button", { name: "Tiếp tục với Google" });
});
