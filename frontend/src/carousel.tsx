import { useCallback, useEffect, useState, type ReactNode } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function Carousel({ label, children }: { label: string; children: ReactNode }) {
  const [ref, api] = useEmblaCarousel({ align: "start", containScroll: "trimSnaps", dragFree: false });
  const [index, setIndex] = useState(0);
  const [snaps, setSnaps] = useState<number[]>([]);

  const refresh = useCallback(() => {
    if (!api) return;
    setIndex(api.selectedScrollSnap());
    setSnaps(api.scrollSnapList());
  }, [api]);

  useEffect(() => {
    if (!api) return;
    refresh();
    api.on("select", refresh);
    api.on("reInit", refresh);
    return () => {
      api.off("select", refresh);
      api.off("reInit", refresh);
    };
  }, [api, refresh]);

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label={label}
      tabIndex={0}
      className="outline-none"
      onKeyDown={(event) => {
        if (event.key === "ArrowRight") api?.scrollNext();
        if (event.key === "ArrowLeft") api?.scrollPrev();
      }}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[11px] uppercase tracking-[0.22em] text-faint">{label}</p>
        <div className="flex items-center gap-2">
          <button type="button" aria-label={`Previous ${label}`} className="grid h-8 w-8 place-items-center rounded-full border border-line text-foam" onClick={() => api?.scrollPrev()}>
            <ChevronLeft size={16} />
          </button>
          <button type="button" aria-label={`Next ${label}`} className="grid h-8 w-8 place-items-center rounded-full border border-line text-foam" onClick={() => api?.scrollNext()}>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      <div ref={ref} className="overflow-hidden">
        <div className="flex touch-pan-y">{children}</div>
      </div>
      <div className="mt-4 flex gap-1.5" aria-hidden>
        {snaps.map((_, snap) => (
          <button key={snap} aria-label={`${label} slide ${snap + 1}`} className={`h-1 rounded-full transition-all ${snap === index ? "w-8 bg-foam" : "w-3 bg-line"}`} onClick={() => api?.scrollTo(snap)} />
        ))}
      </div>
    </div>
  );
}

export function Slide({ children }: { children: ReactNode }) {
  return <div className="min-w-0 shrink-0 grow-0 basis-[86%] pr-3 sm:basis-[48%] lg:basis-[32%]">{children}</div>;
}
