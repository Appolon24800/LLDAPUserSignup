import { useTranslation } from "react-i18next";

export default function ProgressDots({
  current,
  total,
  labels,
}: {
  current: number;
  total: number;
  labels: string[];
}) {
  const { t } = useTranslation();
  return (
    <nav className="progress" aria-label={t("steps.progress", { current, total })}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`progress-dot ${i < current ? "done" : ""} ${i === current ? "current" : ""}`}
          aria-hidden
          title={labels[i]}
        />
      ))}
      <span className="progress-label">
        {t("steps.progress", { current: current + 1, total })} — {labels[current]}
      </span>
    </nav>
  );
}
