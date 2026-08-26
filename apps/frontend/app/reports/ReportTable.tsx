import { stackTableRows } from "@/lib/reports";

export default function ReportTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: string[][];
}) {
  const stacked = stackTableRows(headers, rows);

  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full border-collapse text-sm leading-5">
          <thead>
            <tr>
              {headers.map((header) => (
                <th
                  key={header}
                  className="border-b border-border px-2.5 py-2 text-left text-[11px] font-medium text-muted"
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {headers.map((_, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={`px-2.5 py-2.5 align-top text-foreground ${
                      rowIndex < rows.length - 1 ? "border-b border-border" : ""
                    } ${cellIndex === 0 ? "font-[550]" : ""}`}
                  >
                    {row[cellIndex] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 md:hidden">
        {stacked.map((entry, index) => (
          <article
            key={`${entry.title}-${index}`}
            className="rounded-xl border border-border bg-surface-muted px-3 py-2.5"
          >
            {entry.title ? (
              <p className="text-sm font-[550] leading-5 text-foreground">{entry.title}</p>
            ) : null}
            {entry.fields.length > 0 ? (
              <dl className={`grid gap-x-3 gap-y-1.5 ${entry.title ? "mt-2" : ""} sm:grid-cols-2`}>
                {entry.fields.map((field) => (
                  <div key={field.label}>
                    <dt className="text-[11px] leading-4 text-muted">{field.label}</dt>
                    <dd className="text-sm leading-5 text-foreground">{field.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </article>
        ))}
      </div>
    </>
  );
}
