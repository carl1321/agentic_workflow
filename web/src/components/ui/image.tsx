// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { memo, useCallback, useEffect, useState } from "react";

import { cn } from "~/lib/utils";

function Image({
  className,
  imageClassName,
  imageTransition,
  src,
  alt,
  fallback = null,
}: {
  className?: string;
  imageClassName?: string;
  imageTransition?: boolean;
  src: string;
  alt: string;
  fallback?: React.ReactNode;
}) {
  const [, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);

  useEffect(() => {
    setIsError(false);
    setIsLoading(true);
  }, [src]);

  const handleLoad = useCallback(() => {
    setIsError(false);
    setIsLoading(false);
  }, []);
  const handleError = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      e.currentTarget.style.display = "none";
      console.warn(`Markdown: Image "${e.currentTarget.src}" failed to load`);
      setIsError(true);
    },
    [],
  );

  return (
    <span className={cn("block w-fit overflow-hidden", className)}>
      {isError || !src ? (
        fallback
      ) : (
        <img
          className={cn(
            "size-full object-contain",
            imageTransition && "transition-all duration-200 ease-out",
            imageClassName,
          )}
          src={src}
          alt={alt}
          title={alt ?? "No caption"}
          onLoad={handleLoad}
          onError={handleError}
        />
      )}
    </span>
  );
}

export default memo(Image);
