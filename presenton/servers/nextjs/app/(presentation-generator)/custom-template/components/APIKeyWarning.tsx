import React from "react";
import Header from "@/app/(presentation-generator)/dashboard/components/Header";

export const APIKeyWarning: React.FC = () => {
  return (
    <div className="min-h-screen font-roboto bg-gradient-to-br from-slate-50 to-slate-100">
      <Header />
      <div className="flex items-center justify-center aspect-video mx-auto px-6">
        <div className="text-center space-y-2 my-6 bg-white p-10 rounded-lg shadow-lg">
          <h1 className="text-xl font-bold text-gray-900">
            Template generation is not configured yet.
          </h1>
          <h1 className="text-xl font-bold text-gray-900">Please configure a server-side model key for Slide Generator</h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Set `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `CUSTOM_LLM_API_KEY` in environment variables.
          </p>
        </div>
      </div>
    </div>
  );
}; 
