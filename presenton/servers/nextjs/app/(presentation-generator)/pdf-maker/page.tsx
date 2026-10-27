import React from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import PdfMakerPage from "./PdfMakerPage";

export const dynamic = "force-dynamic";

const page = ({
  searchParams,
}: {
  searchParams?: {
    id?: string;
  };
}) => {
  const queryId =
    typeof searchParams?.id === "string" && searchParams.id.trim()
      ? searchParams.id.trim()
      : null;

  if (!queryId) {
    return (
      <div className="flex flex-col items-center justify-center h-screen">
        <h1 className="text-2xl font-bold">No presentation id found</h1>
        <p className="text-gray-500 pb-4">Please try again</p>
        <Button asChild>
          <Link href="/dashboard">Go to home</Link>
        </Button>
      </div>
    );
  }

  return <PdfMakerPage presentation_id={queryId} />;
};

export default page;
