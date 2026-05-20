import ResultsTabs from "../../components/ResultsTabs";

export default function ResultsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-col">
      <ResultsTabs />
      <div className="flex-1">{children}</div>
    </div>
  );
}
