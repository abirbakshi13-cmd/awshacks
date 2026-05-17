import axios from 'axios';

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

export async function fetchGraph(holdings) {
  const { data } = await http.post('/graph', { holdings });
  return data; // { nodes, edges, portfolio }
}

export async function fetchDigest(ticker) {
  const { data } = await http.get('/digest', { params: { ticker } });
  return data; // { ticker, summary }
}

export async function saveUser(userItem) {
  const { data } = await http.post('/user', userItem);
  return data;
}

export async function fetchPrices(tickers) {
  const { data } = await http.get('/prices', { params: { tickers: tickers.join(',') } });
  return data; // { TICKER: { price, day_change_pct } }
}

export async function sendTestAlert() {
  const { data } = await http.post('/alert/test');
  return data;
}
