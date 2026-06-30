const xlsx = require('xlsx');

function readSkuExcel(filePath) {
  try {
    const workbook = xlsx.readFile(filePath);
    const sheetName = workbook.SheetNames[0];
    const sheet = workbook.Sheets[sheetName];
    
    // Parse to JSON
    const data = xlsx.utils.sheet_to_json(sheet, { header: 1 });
    
    return { success: true, data };
  } catch (error) {
    return { success: false, message: error.message };
  }
}

module.exports = { readSkuExcel };
