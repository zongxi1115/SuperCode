"use client";

import { cn } from "@/lib/utils";
import { GlobeIcon } from "lucide-react";
import { motion } from "motion/react";
import type { ComponentProps, ReactNode } from "react";
import { Children, createElement, isValidElement, useState } from "react";

export type SourcesProps = ComponentProps<"div"> & {
  title?: string;
};

export const Sources = ({
  className,
  title,
  children,
  ...props
}: SourcesProps) => {
  const childArray = Children.toArray(children).filter(isValidElement);

  return (
    <div className={cn("not-prose text-primary text-xs", className)} {...props}>
      {title && (
        <motion.div
          initial={{ opacity: 0, filter: "blur(4px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.3 }}
          className="flex items-center gap-1.5 font-medium text-muted-foreground mb-1.5"
        >
          <GlobeIcon className="size-3.5" />
          <span>{title}</span>
        </motion.div>
      )}
      <div className="flex flex-wrap items-center gap-1.5">
        {childArray.map((child, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, filter: "blur(4px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.25, delay: i * 0.06 }}
          >
            {child}
          </motion.div>
        ))}
      </div>
    </div>
  );
};

function getRootDomain(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname;
    const parts = host.split(".");
    if (parts.length > 2) {
      return parts.slice(-2).join(".");
    }
    return host;
  } catch {
    return url;
  }
}

function getFaviconUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.origin}/favicon.ico`;
  } catch {
    return "";
  }
}

export type SourceTagProps = ComponentProps<"a"> & {
  href: string;
  title?: string;
};

export const SourceTag = ({
  href,
  title,
  className,
  ...props
}: SourceTagProps) => {
  const domain = getRootDomain(href);
  const faviconUrl = getFaviconUrl(href);
  const displayTitle = title || domain;

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md bg-secondary px-2 py-0.5 font-normal text-xs text-secondary-foreground max-w-[220px] truncate no-underline hover:bg-secondary/80 transition-colors",
        className
      )}
      title={displayTitle}
      {...props}
    >
      <img
        src={faviconUrl}
        alt=""
        className="size-3.5 shrink-0 rounded-sm"
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = "none";
        }}
      />
      <span className="truncate">{displayTitle}</span>
    </a>
  );
};
