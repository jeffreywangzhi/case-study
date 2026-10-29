'use client';

import { useEffect, useState } from 'react';
import * as api from '@/lib/api';
import { Button } from '@/components/base';

const usd = (value: string | number) =>
  `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const QUALITY: Record<api.CatalogSuggestion['quality'], { label: string; className: string }> = {
  equivalent: { label: 'Equivalent', className: 'bg-green-50 text-green-800' },
  close: { label: 'Close match', className: 'bg-sky-50 text-sky-800' },
  alternative: { label: 'Alternative', className: 'bg-amber-50 text-amber-800' },
};

/** "save $102.11" / "quote is $125.00 cheaper" / "different unit" for one agreement. */
function SavingText({ agreement }: { agreement: api.CatalogAgreement }) {
  if (!agreement.same_unit) {
    return <span className="text-gray-500">different unit than the quote</span>;
  }
  if (agreement.saving_total === null) return null;
  const total = Number(agreement.saving_total);
  if (total > 0) return <span className="text-green-700 font-medium">save {usd(total)}</span>;
  if (total < 0) {
    return <span className="text-gray-600">the quote is {usd(-total)} cheaper</span>;
  }
  return <span className="text-gray-500">same price as the quote</span>;
}

function AgreementRow({
  agreement,
  onUse,
}: {
  agreement: api.CatalogAgreement;
  onUse: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <div>
        <span className="font-medium text-gray-900">{agreement.supplier_name}</span>{' '}
        <span className="text-gray-700">
          {usd(agreement.unit_price)} / {agreement.unit}
        </span>{' '}
        <span className="text-xs text-gray-400">
          #{agreement.article_number} · qty {Number(agreement.quantity)}
        </span>
        <div className="text-xs">
          <SavingText agreement={agreement} />
        </div>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onUse}>
        Use this agreement
      </Button>
    </div>
  );
}

/** Negotiated agreements that fit an order line, best first, with "Use this agreement". */
export function CatalogPanel({
  suggestions,
  onUse,
}: {
  suggestions: api.CatalogSuggestion[];
  onUse: (suggestion: api.CatalogSuggestion, agreement: api.CatalogAgreement) => void;
}) {
  const [showAllSuppliers, setShowAllSuppliers] = useState(false);
  const [showOtherItems, setShowOtherItems] = useState(false);
  if (suggestions.length === 0) return null;
  const [best, ...otherItems] = suggestions;
  const [bestAgreement, ...otherSuppliers] = best.agreements;

  // By default only the other suppliers that beat the quote; without a comparable quoted
  // price (manual line, different unit), the three cheapest.
  const comparable = otherSuppliers.some((a) => a.saving_total !== null);
  const worthShowing = comparable
    ? otherSuppliers.filter((a) => a.saving_total !== null && Number(a.saving_total) > 0)
    : otherSuppliers.slice(0, 3);
  const visibleSuppliers = showAllSuppliers ? otherSuppliers : worthShowing;

  return (
    <div className="mt-3 rounded-lg border border-accent/40 bg-accent-soft/10 p-3 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-accent-deep">
        Negotiated catalog agreement available
      </p>
      <ItemHeading suggestion={best} />
      <AgreementRow agreement={bestAgreement} onUse={() => onUse(best, bestAgreement)} />

      {otherSuppliers.length > 0 && (
        <div className="space-y-2 border-t border-accent/20 pt-2">
          <p className="text-xs font-medium text-gray-700">
            Same item from {otherSuppliers.length} other supplier
            {otherSuppliers.length > 1 ? 's' : ''}
            {comparable && !showAllSuppliers &&
              ` · ${worthShowing.length} cheaper than the quote`}
          </p>
          {visibleSuppliers.map((agreement) => (
            <AgreementRow key={agreement.article_id} agreement={agreement}
              onUse={() => onUse(best, agreement)} />
          ))}
          {visibleSuppliers.length < otherSuppliers.length || showAllSuppliers ? (
            <button
              type="button"
              className="text-xs text-accent-deep hover:underline"
              onClick={() => setShowAllSuppliers(!showAllSuppliers)}
            >
              {showAllSuppliers ? 'Show fewer suppliers' : `Show all ${otherSuppliers.length} suppliers`}
            </button>
          ) : null}
        </div>
      )}

      {otherItems.length > 0 && (
        <div className="space-y-2 border-t border-accent/20 pt-2">
          <button
            type="button"
            className="text-xs font-medium text-accent-deep hover:underline"
            onClick={() => setShowOtherItems(!showOtherItems)}
          >
            {showOtherItems ? 'Hide' : 'Show'} {otherItems.length} other similar item
            {otherItems.length > 1 ? 's' : ''}
          </button>
          {showOtherItems && otherItems.map((suggestion) => (
            <div key={suggestion.item} className="space-y-1 pt-1">
              <ItemHeading suggestion={suggestion} />
              <AgreementRow agreement={suggestion.agreements[0]}
                onUse={() => onUse(suggestion, suggestion.agreements[0])} />
              {suggestion.agreements.length > 1 && (
                <p className="text-xs text-gray-400">
                  cheapest of {suggestion.agreements.length} suppliers
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Item name, then the badge with its main difference right next to it (not in a line below). */
function ItemHeading({ suggestion }: { suggestion: api.CatalogSuggestion }) {
  const quality = QUALITY[suggestion.quality];
  const [main, ...rest] = suggestion.differences ?? [];
  return (
    <>
      <p className="text-sm text-gray-900">{suggestion.item}</p>
      <p className="text-xs">
        <span className={`inline-flex px-2 py-0.5 font-medium rounded-full ${quality.className}`}>
          {quality.label}
          {main && ` · ${main.aspect}: ${main.detail}`}
        </span>
        {!main && suggestion.quality !== 'equivalent' && (
          <span className="ml-2 text-gray-600">{suggestion.reason}</span>
        )}
      </p>
      {rest.length > 0 && (
        <p className="text-xs text-gray-600">
          Also: {rest.map((d) => `${d.aspect}: ${d.detail}`).join('; ')}
        </p>
      )}
    </>
  );
}

/** Typeahead under a line being typed: catalog items that clearly match, cheapest agreement. */
export function CatalogTypeahead({
  query,
  onPick,
}: {
  query: string;
  onPick: (suggestion: api.CatalogSuggestion, agreement: api.CatalogAgreement) => void;
}) {
  const [results, setResults] = useState<api.CatalogSuggestion[]>([]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) {
      setResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.articles
        .suggest(q)
        .then((found) => !cancelled && setResults(found))
        .catch(() => !cancelled && setResults([]));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  if (results.length === 0) return null;
  return (
    <div className="mt-1 rounded-lg border border-gray-200 bg-white shadow-sm divide-y divide-gray-100">
      <p className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
        From your negotiated catalog
      </p>
      {results.map((suggestion) => {
        const cheapest = suggestion.agreements[0];
        return (
          <button
            key={suggestion.item}
            type="button"
            // onMouseDown so the pick lands before the input's blur hides the list
            onMouseDown={(e) => {
              e.preventDefault();
              onPick(suggestion, cheapest);
            }}
            className="w-full text-left px-3 py-2 hover:bg-accent-soft/10"
          >
            <span className="text-sm text-gray-900">{suggestion.item}</span>
            <span className="block text-xs text-gray-500">
              from {usd(cheapest.unit_price)} / {cheapest.unit} · {cheapest.supplier_name}
              {suggestion.agreements.length > 1 &&
                ` · ${suggestion.agreements.length} suppliers`}
            </span>
          </button>
        );
      })}
    </div>
  );
}
