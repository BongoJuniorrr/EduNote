import React from "react";

import UploadPage from "./components/UploadPage";
import Header from "@/app/(presentation-generator)/dashboard/components/Header";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "EduNote Slides",
  description:
    "EduNote Slides workspace for generating and editing presentations.",
  alternates: {
    canonical: "https://edunote.orzlab.net/slide_pro",
  },
  keywords: [
    "presentation generator",
    "AI presentations",
    "data visualization",
    "automatic presentation maker",
    "professional slides",
    "data-driven presentations",
    "document to presentation",
    "presentation automation",
    "smart presentation tool",
    "business presentations",
  ],
  openGraph: {
    title: "EduNote Slides",
    description:
      "EduNote Slides workspace for generating and editing presentations.",
    type: "website",
    url: "https://edunote.orzlab.net/slide_pro",
    siteName: "EduNote Slides",
  },
  twitter: {
    card: "summary_large_image",
    title: "EduNote Slides",
    description:
      "EduNote Slides workspace for generating and editing presentations.",
    site: "@edunote",
    creator: "@edunote",
  },
};

const page = () => {
  return (
    <div className="relative">
      <Header />
      <div className="flex flex-col items-center justify-center  py-8">
        <h1 className="text-3xl font-semibold font-instrument_sans">
          Create Presentation{" "}
        </h1>
        {/* <p className='text-sm text-gray-500'>We will generate a presentation for you</p> */}
      </div>

      <UploadPage />
    </div>
  );
};

export default page;
