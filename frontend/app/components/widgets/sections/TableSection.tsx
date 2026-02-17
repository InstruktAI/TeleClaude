"use client";

import type { TableSection as TableSectionType } from "@/lib/widgets";

export function TableSectionRenderer({ section }: { section: TableSectionType }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            {section.headers.map((header, i) => (
              <th key={i} className="px-3 py-1.5 text-left font-medium text-muted-foreground">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {section.rows.map((row, rowIdx) => (
            <tr key={rowIdx} className="border-b last:border-0">
              {row.map((cell, cellIdx) => (
                <td key={cellIdx} className="px-3 py-1.5">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {section.caption && (
        <p className="mt-1 text-xs text-muted-foreground">{section.caption}</p>
      )}
    </div>
  );
}
