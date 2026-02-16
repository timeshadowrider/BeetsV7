import { ReactNode } from "react";

export default function Layout({
  nav,
  children
}: {
  nav: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col bg-bg">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <div className="text-lg font-semibold text-gray-100">
          Beets v7 Control Center
        </div>
        {nav}
      </header>
      <main className="flex-1 px-6 py-4 overflow-y-auto">{children}</main>
    </div>
  );
}
