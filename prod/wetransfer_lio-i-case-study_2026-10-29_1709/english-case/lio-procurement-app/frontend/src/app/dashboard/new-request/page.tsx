'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import * as api from '@/lib/api';
import { useCommodityGroups } from '@/lib/hooks/useCommodityGroups';
import { Button, Input, Alert, Loader } from '@/components/base';

interface OrderLine {
  positionDescription: string;
  unitPrice: number;
  amount: number;
  unit: string;
  totalPrice: number;
  lineType?: api.ExtractedLineType;
}

const roundCents = (value: number) => Math.round(value * 100) / 100;

const isPdfFile = (file: File) =>
  file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');

export default function NewRequestPage() {
  const router = useRouter();
  const { data: commodityGroups } = useCommodityGroups();

  // Form state
  const [requestorName, setRequestorName] = useState('');
  const [title, setTitle] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [vatId, setVatId] = useState('');
  const [department, setDepartment] = useState('');
  const [commodityGroupId, setCommodityGroupId] = useState<number | null>(null);
  const [orderLines, setOrderLines] = useState<OrderLine[]>([]);
  // Cost breakdown on top of the order lines (which are only what is being bought).
  const [shippingAmount, setShippingAmount] = useState<number>(0);
  const [feesAmount, setFeesAmount] = useState<number>(0);
  const [taxAmount, setTaxAmount] = useState<number>(0);
  // Alternatives / optional items from the quote: not part of the request unless added.
  const [excludedLines, setExcludedLines] = useState<OrderLine[]>([]);

  // Always derived, never typed in: total = order lines + shipping + fees + tax.
  const itemsTotal = roundCents(orderLines.reduce((sum, line) => sum + line.totalPrice, 0));
  const totalCost = roundCents(itemsTotal + shippingAmount + feesAmount + taxAmount);

  // UI state
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [warning, setWarning] = useState('');
  const [reviewItems, setReviewItems] = useState<api.ExtractionWarning[]>([]);
  const [extracting, setExtracting] = useState(false);

  // The requestor is the signed-in user, never something on the vendor's quote: pre-fill
  // name and department from their profile, without overwriting anything already typed.
  useEffect(() => {
    api.auth
      .me()
      .then(({ profile }) => {
        setRequestorName((current) => current || profile.full_name || '');
        setDepartment((current) => current || profile.department || '');
      })
      .catch(() => {
        // Non-fatal: the user can type both fields.
      });
  }, []);

  // Handle file upload and extraction
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const uploadedFile = e.target.files?.[0];
    if (!uploadedFile) return;

    if (!isPdfFile(uploadedFile)) {
      setError('Please upload a PDF file');
      return;
    }

    setFile(uploadedFile);
    setError('');
    setSuccess('');
    setWarning('');
    setReviewItems([]);
    setExtracting(true);

    try {
      // One call: the server reads the PDF's text and page images, then checks the numbers.
      const extractionResult = await api.extraction.extractPdf(uploadedFile);

      if (!extractionResult.success || !extractionResult.data) {
        throw new Error(extractionResult.error || 'Failed to extract data');
      }

      const extracted = extractionResult.data;

      // Auto-fill form (including commodity group from extraction)
      setTitle(extracted.title || '');
      setVendorName(extracted.vendorName || '');
      setVatId(extracted.vatId || '');
      setOrderLines(extracted.orderLines || []);
      setExcludedLines(extracted.excludedLines || []);
      setShippingAmount(extracted.shippingAmount || 0);
      setFeesAmount(extracted.feesAmount || 0);
      setTaxAmount(extracted.taxAmount || 0);

      if (extracted.commodityGroupId) {
        setCommodityGroupId(extracted.commodityGroupId);
      }

      // Show warnings for missing fields
      if (extractionResult.missingFields && extractionResult.missingFields.length > 0) {
        setWarning(
          `⚠️ Could not extract: ${extractionResult.missingFields.join(', ')}. Please fill in these fields manually.`
        );
      }

      // Specific reasons to double-check, instead of a blanket "success".
      const warnings = extractionResult.warnings || [];
      setReviewItems(warnings);
      setSuccess(
        extractionResult.status === 'verified'
          ? '✓ PDF extracted and verified: the lines, tax and totals match the quote. Review and submit.'
          : '✓ PDF extracted. Some values need your review (see below) before you submit.'
      );
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      console.error('Extraction error:', err);
      setError(err instanceof Error ? err.message : 'Failed to extract data from PDF');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } finally {
      setExtracting(false);
    }
  };

  // Add order line manually
  const addOrderLine = () => {
    setOrderLines([
      ...orderLines,
      {
        positionDescription: '',
        unitPrice: 0,
        amount: 1,
        unit: '',
        totalPrice: 0,
      },
    ]);
  };

  // Update order line
  const updateOrderLine = (index: number, field: keyof OrderLine, value: string | number) => {
    const updated = [...orderLines];
    updated[index] = { ...updated[index], [field]: value };
    
    // Auto-calculate total price
    if (field === 'unitPrice' || field === 'amount') {
      updated[index].totalPrice = roundCents(updated[index].unitPrice * updated[index].amount);
    }

    setOrderLines(updated);
  };

  // Remove order line
  const removeOrderLine = (index: number) => {
    setOrderLines(orderLines.filter((_, i) => i !== index));
  };

  // Move an alternative / optional item from the quote into the request
  const includeExcludedLine = (index: number) => {
    setOrderLines([...orderLines, { ...excludedLines[index], lineType: 'item' }]);
    setExcludedLines(excludedLines.filter((_, i) => i !== index));
  };

  // Submit form
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setWarning('');

    // Validation with scroll to top on error
    if (!commodityGroupId) {
      setError('Please select a commodity group');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }

    if (orderLines.length === 0) {
      setError('Please add at least one order line');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }

    try {
      const created = await api.requests.create({
        requestorName,
        titleShortDescription: title,
        vendorName,
        vatId,
        commodityGroupId: commodityGroupId,
        totalCost,
        shippingAmount,
        feesAmount,
        taxAmount,
        department,
        orderLines,
      });

      // Attach the original PDF (if one was uploaded) so it shows on the detail page.
      if (file) {
        try {
          await api.requests.uploadDocument(created.id, file);
        } catch {
          // Non-fatal — the request itself was created.
        }
      }

      setSuccess('Request created successfully! Redirecting...');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      setTimeout(() => {
        router.push('/dashboard/requests');
        router.refresh();
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create request');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight text-ink">New Procurement Request</h1>
        <p className="text-gray-600 mt-2">
          Upload a vendor offer PDF or fill in the details manually
        </p>
      </div>

      {error && <Alert variant="error" className="mb-6">{error}</Alert>}
      {warning && <Alert variant="warning" className="mb-6">{warning}</Alert>}
      {reviewItems.length > 0 && (
        <Alert variant="warning" className="mb-6">
          <p className="font-medium mb-1">Please review before submitting:</p>
          <ul className="list-disc pl-5 space-y-1">
            {reviewItems.map((item, i) => (
              <li key={i}>{item.message}</li>
            ))}
          </ul>
        </Alert>
      )}
      {success && <Alert variant="success" className="mb-6">{success}</Alert>}

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* PDF Upload Section */}
        <div className="lio-card p-6">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Upload Vendor Offer (Optional)</h2>
          <p className="text-sm text-gray-600 mb-4">
            Upload a PDF to automatically extract vendor details and order items
          </p>

          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-accent-deep/50 transition-colors">
            <input
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleFileChange}
              className="hidden"
              id="pdf-upload"
              disabled={extracting}
            />
            <label htmlFor="pdf-upload" className="cursor-pointer">
              {extracting ? (
                <div className="flex flex-col items-center">
                  <Loader size="lg" />
                  <p className="mt-4 text-sm text-gray-600">Extracting data from PDF...</p>
                </div>
              ) : file ? (
                <div>
                  <svg
                    className="mx-auto h-12 w-12 text-green-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                  <p className="mt-2 text-sm font-medium text-gray-900">{file.name}</p>
                  <p className="mt-1 text-xs text-gray-500">Click to upload a different file</p>
                </div>
              ) : (
                <div>
                  <svg
                    className="mx-auto h-12 w-12 text-gray-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                  <p className="mt-2 text-sm text-gray-600">
                    Click to upload or drag and drop
                  </p>
                  <p className="mt-1 text-xs text-gray-500">PDF up to 10MB</p>
                </div>
              )}
            </label>
          </div>
        </div>

        {/* Request Details */}
        <div className="lio-card p-6 space-y-4">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Request Details</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input
              label="Requestor Name *"
              value={requestorName}
              onChange={(e) => setRequestorName(e.target.value)}
              required
              placeholder="John Doe"
            />

            <Input
              label="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="IT Department"
            />
          </div>

          <Input
            label="Title / Short Description *"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="Adobe Creative Cloud Subscription"
          />
        </div>

        {/* Vendor Information */}
        <div className="lio-card p-6 space-y-4">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-4">Vendor Information</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input
              label="Vendor Name *"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              required
              placeholder="Adobe Systems"
            />

            <Input
              label="Tax ID"
              value={vatId}
              onChange={(e) => setVatId(e.target.value)}
              placeholder="12-3456789"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Commodity Group *
            </label>
            <select
              value={commodityGroupId || ''}
              onChange={(e) => setCommodityGroupId(Number(e.target.value))}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 focus:ring-2 focus:ring-accent-deep/60 focus:border-accent-deep/40"
            >
              <option value="">
                {commodityGroups ? 'Select a commodity group' : 'Loading...'}
              </option>
              {commodityGroups?.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.id} - {group.category} - {group.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Order Lines */}
        <div className="lio-card p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-ink">Order Lines *</h2>
            <Button type="button" onClick={addOrderLine} variant="outline" size="sm">
              + Add Line
            </Button>
          </div>

          {orderLines.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No order lines yet. Add one to get started.
            </div>
          ) : (
            <div className="space-y-4">
              {orderLines.map((line, index) => (
                <div key={index} className="border border-gray-200 rounded-lg p-4">
                  <div className="flex items-start justify-between mb-4">
                    <h3 className="text-sm font-medium text-gray-700">Line {index + 1}</h3>
                    <button
                      type="button"
                      onClick={() => removeOrderLine(index)}
                      className="text-red-600 hover:text-red-700 text-sm"
                    >
                      Remove
                    </button>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
                    <div className="lg:col-span-2">
                      <Input
                        label="Description"
                        value={line.positionDescription}
                        onChange={(e) =>
                          updateOrderLine(index, 'positionDescription', e.target.value)
                        }
                        required
                        placeholder="Item description"
                      />
                    </div>

                    <Input
                      label="Unit Price ($)"
                      type="number"
                      step="0.01"
                      value={line.unitPrice}
                      onChange={(e) =>
                        updateOrderLine(index, 'unitPrice', parseFloat(e.target.value) || 0)
                      }
                      required
                    />

                    <Input
                      label="Amount"
                      type="number"
                      step="0.01"
                      value={line.amount}
                      onChange={(e) =>
                        updateOrderLine(index, 'amount', parseFloat(e.target.value) || 1)
                      }
                      required
                    />

                    <Input
                      label="Unit"
                      value={line.unit}
                      onChange={(e) => updateOrderLine(index, 'unit', e.target.value)}
                      required
                      placeholder="pcs, licenses, etc."
                    />
                  </div>

                  <div className="mt-2 text-right">
                    <span className="text-sm text-gray-600">Total: </span>
                    <span className="text-lg font-semibold tracking-tight text-ink">
                      ${line.totalPrice.toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Alternatives / optional items the quote lists but doesn't include in its total */}
        {excludedLines.length > 0 && (
          <div className="lio-card p-6">
            <h2 className="text-xl font-semibold tracking-tight text-ink mb-1">
              Not included: alternatives &amp; optional items
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              The quote lists these as either-or variants or add-ons; they are not part of its
              total. Add one only if you want it instead of, or on top of, the quoted items.
            </p>
            <div className="space-y-2">
              {excludedLines.map((line, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between gap-4 border border-dashed border-gray-300 rounded-lg p-3"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {line.positionDescription}
                      <span className="ml-2 inline-flex px-2 py-0.5 text-xs font-medium rounded-full bg-amber-50 text-amber-800">
                        {line.lineType === 'optional' ? 'Optional' : 'Alternative'}
                      </span>
                    </p>
                    <p className="text-sm text-gray-500">
                      {line.amount} {line.unit} × ${line.unitPrice.toFixed(2)} = $
                      {line.totalPrice.toFixed(2)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => includeExcludedLine(index)}
                  >
                    Add to request
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Cost breakdown: total = order lines + shipping + fees + tax */}
        <div className="bg-accent-soft/20 border-2 border-accent/40 rounded-lg p-6 space-y-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-700">Items (order lines)</span>
            <span className="font-medium text-gray-900">${itemsTotal.toFixed(2)}</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Input
              label="Shipping ($)"
              type="number"
              step="0.01"
              min="0"
              value={shippingAmount}
              onChange={(e) => setShippingAmount(parseFloat(e.target.value) || 0)}
            />
            <Input
              label="Fees ($)"
              type="number"
              step="0.01"
              min="0"
              value={feesAmount}
              onChange={(e) => setFeesAmount(parseFloat(e.target.value) || 0)}
            />
            <Input
              label="Sales Tax ($)"
              type="number"
              step="0.01"
              min="0"
              value={taxAmount}
              onChange={(e) => setTaxAmount(parseFloat(e.target.value) || 0)}
            />
          </div>
          <div className="flex items-center justify-between border-t border-accent/30 pt-4">
            <span className="text-lg font-medium text-gray-900">Total Cost</span>
            <span className="text-3xl font-bold text-accent-deep">
              ${totalCost.toFixed(2)}
            </span>
          </div>
        </div>

        {/* Submit */}
        <div className="flex items-center justify-end space-x-4">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.back()}
          >
            Cancel
          </Button>
          <Button type="submit" size="lg">
            Create Request
          </Button>
        </div>
      </form>
    </div>
  );
}

