import { WorkspaceProvider } from "@/components/workspace/WorkspaceProvider";
import { WorkspaceShell } from "@/components/workspace/WorkspaceShell";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceProvider><WorkspaceShell>{children}</WorkspaceShell></WorkspaceProvider>;
}
