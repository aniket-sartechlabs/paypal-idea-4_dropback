import { AgGridReact } from 'ag-grid-react'
import { themeQuartz, type ColDef, type RowClickedEvent } from 'ag-grid-community'

const gridTheme = themeQuartz.withParams({
  backgroundColor: '#ffffff',
  foregroundColor: '#1e293b',
  headerBackgroundColor: '#f8fafc',
  headerTextColor: '#475569',
  borderColor: '#e2e8f0',
  rowHoverColor: '#f1f5f9',
  fontFamily: 'DM Sans, Inter, system-ui, -apple-system, sans-serif',
  fontSize: 13,
  headerFontSize: 11,
  headerFontWeight: 700,
  rowHeight: 72,
  headerHeight: 46,
})

export type GridTableProps = {
  rowData: any[]
  columnDefs: ColDef<any>[]
  pagination?: boolean
  paginationPageSize?: number
  quickFilterText?: string
  domLayout?: 'normal' | 'autoHeight' | 'print'
  onRowClicked?: (event: RowClickedEvent<any>) => void
  loading?: boolean
  rowHeight?: number
}

const defaultColDef: ColDef = {
  sortable: true,
  resizable: true,
  minWidth: 92,
  wrapHeaderText: true,
  autoHeaderHeight: true,
}

export default function GridTable({
  rowData,
  columnDefs,
  pagination = false,
  paginationPageSize = 10,
  quickFilterText,
  domLayout = 'normal',
  onRowClicked,
  loading = false,
  rowHeight = 72,
}: GridTableProps) {
  return (
    <AgGridReact<any>
      theme={gridTheme}
      rowData={rowData}
      columnDefs={columnDefs}
      defaultColDef={defaultColDef}
      pagination={pagination}
      paginationPageSize={paginationPageSize}
      paginationPageSizeSelector={[10, 20, 50]}
      quickFilterText={quickFilterText}
      suppressCellFocus
      domLayout={domLayout}
      onRowClicked={onRowClicked}
      loading={loading}
      rowHeight={rowHeight}
      animateRows
      enableCellTextSelection
      getRowId={params => String(params.data.id || params.data.order_id || params.data.product_id)}
    />
  )
}
