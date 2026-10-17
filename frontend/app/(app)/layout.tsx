import { AppHeader } from "@/components/app/AppHeader";
import { EngagementProvider } from "@/components/app/EngagementProvider";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <EngagementProvider>
      <div className="flex min-h-dvh flex-col lg:h-dvh">
        <AppHeader />
        <main className="flex min-h-0 flex-1 flex-col px-4 pt-4 pb-4 md:px-6 md:pb-6">{children}</main>
      </div>
    </EngagementProvider>
  );
}
