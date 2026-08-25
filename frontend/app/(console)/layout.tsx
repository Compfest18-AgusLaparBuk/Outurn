import { redirect } from "next/navigation";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  void children;
  redirect("/");
}
