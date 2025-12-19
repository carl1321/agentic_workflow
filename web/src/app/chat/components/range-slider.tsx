"use client";

import { useState, useRef, useEffect } from "react";

interface RangeSliderProps {
  min: number;
  max: number;
  value: [number, number];
  onChange: (value: [number, number]) => void;
  step?: number;
  disabled?: boolean;
  className?: string;
  showLabels?: boolean;
}

export function RangeSlider({
  min,
  max,
  value,
  onChange,
  step = 0.1,
  disabled = false,
  className = "",
  showLabels = true,
}: RangeSliderProps) {
  const [isDragging, setIsDragging] = useState<"min" | "max" | null>(null);
  const sliderRef = useRef<HTMLDivElement>(null);

  const getPercentage = (val: number) => {
    return ((val - min) / (max - min)) * 100;
  };

  const getValueFromPercentage = (percentage: number) => {
    const rawValue = min + (percentage / 100) * (max - min);
    return Math.round(rawValue / step) * step;
  };

  const handleMouseDown = (type: "min" | "max") => {
    if (disabled) return;
    setIsDragging(type);
  };

  const handleMouseMove = (e: MouseEvent) => {
    if (!isDragging || !sliderRef.current) return;

    const rect = sliderRef.current.getBoundingClientRect();
    const percentage = Math.max(
      0,
      Math.min(100, ((e.clientX - rect.left) / rect.width) * 100)
    );
    const newValue = getValueFromPercentage(percentage);

    if (isDragging === "min") {
      const clampedValue = Math.max(min, Math.min(newValue, value[1] - step));
      onChange([clampedValue, value[1]]);
    } else {
      const clampedValue = Math.min(max, Math.max(newValue, value[0] + step));
      onChange([value[0], clampedValue]);
    }
  };

  const handleMouseUp = () => {
    setIsDragging(null);
  };

  useEffect(() => {
    if (isDragging) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      return () => {
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
      };
    }
  }, [isDragging, value]);

  const minPercentage = getPercentage(value[0]);
  const maxPercentage = getPercentage(value[1]);

  return (
    <div className={`relative ${className}`}>
      {showLabels && (
        <div className="flex justify-between mb-2 text-xs text-slate-500 dark:text-slate-400">
          <span>{min}</span>
          <span>{max}</span>
        </div>
      )}
      <div
        ref={sliderRef}
        className="relative h-2 bg-slate-200 dark:bg-slate-700 rounded-full cursor-pointer"
      >
        {/* Active range */}
        <div
          className="absolute h-full bg-blue-500 rounded-full"
          style={{
            left: `${minPercentage}%`,
            width: `${maxPercentage - minPercentage}%`,
          }}
        />
        {/* Min thumb */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-blue-500 rounded-full cursor-grab active:cursor-grabbing shadow-md hover:scale-110 transition-transform"
          style={{ left: `calc(${minPercentage}% - 8px)` }}
          onMouseDown={(e) => {
            e.preventDefault();
            handleMouseDown("min");
          }}
        />
        {/* Max thumb */}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-blue-500 rounded-full cursor-grab active:cursor-grabbing shadow-md hover:scale-110 transition-transform"
          style={{ left: `calc(${maxPercentage}% - 8px)` }}
          onMouseDown={(e) => {
            e.preventDefault();
            handleMouseDown("max");
          }}
        />
      </div>
      <div className="flex justify-between mt-2 text-sm text-slate-700 dark:text-slate-300">
        <span>{value[0].toFixed(1)}</span>
        <span>{value[1].toFixed(1)}</span>
      </div>
    </div>
  );
}

