import { AgGridReact } from 'ag-grid-react'
import { themeQuartz, type ColDef, type RowClickedEvent } from 'ag-grid-community'

const gridTheme = themeQuartz.withParams({
  backgroundColor: '#ffffff',
  foregroundColor: '#1e293b',
  headerBackgroundColor: '#f8fafc',
  headerTextColor: '#475569',
  borderColor: '#e2e8f0',
  rowHoverColor: '#f1f5f9',
  fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
  fontSize: 13,
  headerFontSize: 11,
  headerFontWeight: 700,
  rowHeight: 56,
  headerHeight: 44,
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
}

const defaultColDef: ColDef = {
  sortable: true,
  resizable: true,
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
      animateRows
      enableCellTextSelection
    />
  )
}
