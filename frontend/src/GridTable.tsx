import { AgGridReact } from 'ag-grid-react'
import { themeQuartz, type ColDef } from 'ag-grid-community'

const gridTheme = themeQuartz.withParams({
  backgroundColor: '#ffffff', foregroundColor: '#29333a', headerBackgroundColor: '#f7f8f6',
  headerTextColor: '#687178', borderColor: '#eceeea', rowHoverColor: '#f7faf8', fontFamily: 'Inter, system-ui, sans-serif',
  fontSize: 13, headerFontSize: 11, headerFontWeight: 650, rowHeight: 52, headerHeight: 42,
})

export type GridTableProps = {
  rowData: any[]
  columnDefs: ColDef<any>[]
  pagination?: boolean
  paginationPageSize?: number
  quickFilterText?: string
  domLayout?: 'normal' | 'autoHeight' | 'print'
}

export default function GridTable({ rowData, columnDefs, pagination = false, paginationPageSize, quickFilterText, domLayout = 'normal' }: GridTableProps) {
  return <AgGridReact<any> theme={gridTheme} rowData={rowData} columnDefs={columnDefs} pagination={pagination} paginationPageSize={paginationPageSize} quickFilterText={quickFilterText} suppressCellFocus domLayout={domLayout} />
}
