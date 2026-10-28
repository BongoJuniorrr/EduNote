"use client";

import Wrapper from "@/components/Wrapper";
import React from "react";
import Link from "next/link";
import BackBtn from "@/components/BackBtn";
import { usePathname } from "next/navigation";
import HeaderNav from "@/app/(presentation-generator)/components/HeaderNab";
import { Layout, FilePlus2 } from "lucide-react";
import { trackEvent, MixpanelEvent } from "@/utils/mixpanel";
import { withBasePath } from "@/utils/basePath";
const Header = () => {
  const pathname = usePathname();
  return (
    <div className="bg-[#5146E5] w-full shadow-lg sticky top-0 z-50">
      <Wrapper>
        <div className="flex items-center justify-between py-1">
          <div className="flex items-center gap-3">
            {(pathname !== "/upload" && pathname !== "/dashboard") && <BackBtn />}
            <Link href="/dashboard" onClick={() => trackEvent(MixpanelEvent.Navigation, { from: pathname, to: "/dashboard" })}>
              <img
                src={withBasePath("/logo-white.png")}
                alt="EduNote Slides"
                className="h-16"
              />
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/custom-template"
              prefetch={false}
              onClick={() => trackEvent(MixpanelEvent.Navigation, { from: pathname, to: "/custom-template" })}
              className="relative flex items-center gap-2 px-3 py-2 text-white hover:bg-primary/80 rounded-md transition-colors outline-none"
              role="menuitem"
            >
              <span className="absolute -right-2 -top-2 rounded-full bg-orange-400 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-950 shadow-md">
                Beta
              </span>
              <FilePlus2 className="w-5 h-5" />
              <span className="text-sm font-medium font-inter">Create Template</span>
            </Link>
            <Link
              href="/template-preview"
              prefetch={false}
              onClick={() => trackEvent(MixpanelEvent.Navigation, { from: pathname, to: "/template-preview" })}
              className="flex items-center gap-2 px-3 py-2 text-white hover:bg-primary/80 rounded-md transition-colors outline-none"
              role="menuitem"
            >
              <Layout className="w-5 h-5" />
              <span className="text-sm font-medium font-inter">Templates</span>
            </Link>
            <HeaderNav />
          </div>
        </div>
      </Wrapper>
    </div>
  );
};

export default Header;
