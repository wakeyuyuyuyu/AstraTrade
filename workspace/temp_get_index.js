const { mxData } = require('./src/skills/mx-data');

(async () => {
  const indices = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH'];
  const results = [];
  
  for (const symbol of indices) {
    try {
      const r = await mxData.getPrice({ symbol });
      results.push({ symbol, data: r });
    } catch(e) { 
      results.push({ symbol, error: e.message }); 
    }
  }
  
  console.log(JSON.stringify(results));
})();
