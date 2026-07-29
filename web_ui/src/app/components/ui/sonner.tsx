"use client";

import { Toaster as Sonner, ToasterProps } from "sonner";

// `theme` defaults to the app's light palette rather than sonner's "system", so
// toasts can never be dark over a light app. App passes the resolved theme from
// useTheme(), which is the app's actual painted scheme (#191).
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  );
};

export { Toaster };
