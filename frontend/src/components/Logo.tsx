export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span className={`brand-gradient inline-flex items-center justify-center rounded-xl shadow-sm ${className}`}>
      <svg viewBox="0 0 32 32" className="h-[70%] w-[70%]" aria-hidden>
        <path d="M16 3 6 7.5v7c0 6.6 4.3 11.8 10 13.5 5.7-1.7 10-6.9 10-13.5v-7z" fill="white" fillOpacity="0.95" />
        <path
          d="m11.5 16 3.2 3.2 6-6.4"
          stroke="var(--brand)"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
