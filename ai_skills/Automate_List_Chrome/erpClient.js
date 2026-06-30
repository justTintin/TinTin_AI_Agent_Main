const axios = require('axios');
const crypto = require('crypto');

class WdtClient {
  constructor(baseUrl, appkey, appsecret, sid) {
    this.baseUrl = baseUrl.endsWith('/') ? baseUrl : baseUrl + '/';
    this.appkey = appkey;
    this.appsecret = appsecret;
    this.sid = sid;
  }

  _signRequest(params) {
    const keys = Object.keys(params).sort();
    let query = [];
    for (const key of keys) {
      if (key === 'sign') continue;
      const val = String(params[key]);
      const kLen = Buffer.byteLength(key, 'utf8');
      const vLen = Buffer.byteLength(val, 'utf8');
      
      const padZero = (num, length) => String(num).padStart(length, '0');
      query.push(`${padZero(kLen, 2)}-${key}:${padZero(vLen, 4)}-${val}`);
    }
    
    const queryStr = query.join(';') + this.appsecret;
    return crypto.createHash('md5').update(queryStr, 'utf8').digest('hex');
  }

  async callApi(apiMethod, params = {}) {
    const reqParams = { ...params };
    
    reqParams.appkey = this.appkey;
    reqParams.sid = this.sid;
    reqParams.timestamp = Math.floor(Date.now() / 1000).toString();
    reqParams.format = 'json';
    reqParams.v = '1.0';
    
    reqParams.sign = this._signRequest(reqParams);

    const url = this.baseUrl + apiMethod + '.php';
    const data = new URLSearchParams(reqParams).toString();

    try {
      const response = await axios.post(url, data, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        timeout: 60000
      });
      return response.data;
    } catch (error) {
      return { code: -1, message: error.message };
    }
  }

  async searchCombinations(pageNo = 1, pageSize = 100, startTime = null, endTime = null) {
    const params = {
      page_no: pageNo.toString(),
      page_size: pageSize.toString()
    };
    if (startTime) params.start_time = startTime;
    if (endTime) params.end_time = endTime;

    return await this.callApi('suites_query', params);
  }
}

module.exports = WdtClient;
