"use client";

import { useState } from "react";
import { Minus, Plus } from "lucide-react";
import { Button } from "~/components/ui/button";

interface StepperProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  precision?: number;
  disabled?: boolean;
  className?: string;
}

export function Stepper({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  precision = 2,
  disabled = false,
  className = "",
}: StepperProps) {
  const [inputValue, setInputValue] = useState(value.toString());

  const formatValue = (val: number): number => {
    return Number(val.toFixed(precision));
  };

  const clampValue = (val: number): number => {
    return Math.max(min, Math.min(max, val));
  };

  const handleDecrease = () => {
    const newValue = clampValue(formatValue(value - step));
    onChange(newValue);
    setInputValue(newValue.toString());
  };

  const handleIncrease = () => {
    const newValue = clampValue(formatValue(value + step));
    onChange(newValue);
    setInputValue(newValue.toString());
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputVal = e.target.value;
    setInputValue(inputVal);

    const numVal = parseFloat(inputVal);
    if (!isNaN(numVal)) {
      const clamped = clampValue(formatValue(numVal));
      onChange(clamped);
    }
  };

  const handleInputBlur = () => {
    const numVal = parseFloat(inputValue);
    if (isNaN(numVal)) {
      setInputValue(value.toString());
    } else {
      const clamped = clampValue(formatValue(numVal));
      setInputValue(clamped.toString());
      onChange(clamped);
    }
  };

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={handleDecrease}
        disabled={disabled || value <= min}
        className="h-8 w-8"
      >
        <Minus className="h-4 w-4" />
      </Button>
      <input
        type="number"
        value={inputValue}
        onChange={handleInputChange}
        onBlur={handleInputBlur}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        className="w-24 px-3 py-1.5 text-center border border-slate-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={handleIncrease}
        disabled={disabled || value >= max}
        className="h-8 w-8"
      >
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
}

