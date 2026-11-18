#include <Arduino.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <WiFi.h>
#include <WebServer.h>
#include <math.h>

// ==================== PIN DEFINITIONS ====================
#define TFT_CS        5
#define TFT_DC        21
#define TFT_RST       22
#define PIN_POT_BG    34
#define PIN_POT_DRIFT 35
#define PIN_SW_SOURCE 25
#define PIN_SW_FAULT  26
#define PIN_SW_MODE   27
#define PIN_LED_GREEN 16
#define PIN_LED_YEL   17
#define PIN_LED_RED   32
#define PIN_BUZZER    33

// ==================== CUSTOM RGB565 UI COLORS ====================
#define COL_BG_DARK   0x0842  // Deep slate background
#define COL_CARD_BG   0x10A4  // Dark instrument panel card
#define COL_MUTED     0x9CD3  // Soft grey-blue label text
#define COL_ORANGE    0xFD20  // High-contrast amber/orange

// ==================== WI-FI SOFT-AP CONFIG ====================
const char* AP_SSID = "SPECTRA-Control";
const char* AP_PASS = "raddaes123";
WebServer server(80);

Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

// ==================== RAD-DAES CONSTANTS & STATE ====================
static const int NUM_W = 6;
static const int FANO_LEN = 12;
static const float GATE_M2  = 24.0f;
static const float ALARM_M2 = 28.0f;
static const float SHRINK   = 1.50f;
static const float W_BASE[NUM_W] = {0.34f, 0.26f, 0.16f, 0.11f, 0.08f, 0.05f};
static const float SRC_ADD[NUM_W] = {18.0f, 14.0f, 9.0f, 42.0f, 2.0f, 0.5f};

float mu[NUM_W], cov[NUM_W][NUM_W], eigVec[NUM_W], ring[NUM_W][FANO_LEN], lastObs[NUM_W];
float lambdaMax = 10.0f, alpha = 0.08f, driftPhase = 0.0f;
float lastM2 = 0.0f, lastGross = 100.0f;
int lastGate = 0;
bool lastAlarm = false;
int ringIdx = 0, ringCnt = 0;
uint32_t lastTick = 0, sampleIdx = 0;
bool serSrc = false, serFlt = false, serDaes = true;

// ==================== MOBILE WEB CONTROL PANEL ====================
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>S.P.E.C.T.R.A. Wireless Toggle Deck</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #f8fafc; --muted: #94a3b8;
    --green: #22c55e; --red: #ef4444; --amber: #f59e0b; --blue: #38bdf8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: system-ui, -apple-system, sans-serif; }
  body { background: var(--bg); color: var(--text); padding: 14px; max-width: 460px; margin: 0 auto; }
  .hdr { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 12px; }
  .title { font-size: 1.05rem; font-weight: 800; letter-spacing: 0.04em; }
  .sub { font-size: 0.72rem; color: var(--muted); margin-top: 2px; }
  .badge { padding: 6px 10px; border-radius: 8px; font-weight: 800; font-size: 0.78rem; color: #000; background: var(--green); }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }
  .metric { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px; text-align: center; }
  .metric .lbl { font-size: 0.68rem; color: var(--muted); text-transform: uppercase; }
  .metric .val { font-size: 1.15rem; font-weight: 800; margin-top: 3px; font-variant-numeric: tabular-nums; }
  .sw-card { background: var(--card); border: 2px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; -webkit-tap-highlight-color: transparent; }
  .sw-name { font-size: 0.96rem; font-weight: 700; }
  .sw-desc { font-size: 0.74rem; color: var(--muted); margin-top: 3px; }
  .pill { min-width: 84px; text-align: center; padding: 8px 12px; border-radius: 999px; font-weight: 800; font-size: 0.8rem; background: #334155; color: var(--text); }
  .on-src { border-color: var(--red); } .on-src .pill { background: var(--red); color: #fff; }
  .on-flt { border-color: var(--amber); } .on-flt .pill { background: var(--amber); color: #000; }
  .on-daes { border-color: var(--blue); } .on-daes .pill { background: var(--blue); color: #000; }
  .reset-btn { width: 100%; padding: 12px; border-radius: 12px; border: 1px solid var(--border); background: #1e293b; color: var(--muted); font-weight: 700; font-size: 0.82rem; cursor: pointer; margin-top: 4px; }
</style>
</head>
<body>
  <div class="hdr">
    <div>
      <div class="title">S.P.E.C.T.R.A. DECK</div>
      <div class="sub">ESP32 Wi-Fi Switch Box &bull; Sample #<span id="smp">0</span></div>
    </div>
    <div id="gateBadge" class="badge">NORMAL</div>
  </div>
  <div class="grid">
    <div class="metric"><div class="lbl">Threat (M&sup2;)</div><div class="val" id="m2">0.0</div></div>
    <div class="metric"><div class="lbl">Adapt Speed</div><div class="val" id="alp">8.0%</div></div>
    <div class="metric"><div class="lbl">Drift Score</div><div class="val" id="eig">10.0</div></div>
  </div>
  <div id="cardSrc" class="sw-card" onclick="toggleSw(1)">
    <div><div class="sw-name">SW1: SOURCE INJECT</div><div class="sw-desc">Synthetic Cs-137 Spike (Pin 25)</div></div>
    <div id="pillSrc" class="pill">OFF</div>
  </div>
  <div id="cardFlt" class="sw-card" onclick="toggleSw(2)">
    <div><div class="sw-name">SW2: FAULT INJECT</div><div class="sw-desc">Frozen Count / Dropout (Pin 26)</div></div>
    <div id="pillFlt" class="pill">OFF</div>
  </div>
  <div id="cardDaes" class="sw-card on-daes" onclick="toggleSw(3)">
    <div><div class="sw-name">SW3: ADAPTATION MODE</div><div class="sw-desc">DAES Eigen-Scaling vs. Fixed (Pin 27)</div></div>
    <div id="pillDaes" class="pill">DAES ON</div>
  </div>
  <button class="reset-btn" onclick="toggleSw(0)">RESET TO CLEAN DAES BASELINE (1, 0, 0)</button>
<script>
function render(d) {
  document.getElementById('smp').textContent = d.sample;
  document.getElementById('m2').textContent = d.m2.toFixed(1) + '/28';
  document.getElementById('alp').textContent = (d.alpha * 100).toFixed(1) + '%';
  document.getElementById('eig').textContent = d.eig.toFixed(1);
  const b = document.getElementById('gateBadge');
  if (d.alarm) { b.textContent = 'ALARM!'; b.style.background = '#ef4444'; b.style.color = '#fff'; }
  else if (d.gate === 1) { b.textContent = 'FAULT LOCK'; b.style.background = '#f59e0b'; b.style.color = '#000'; }
  else if (d.gate === 2) { b.textContent = 'SOURCE HOLD'; b.style.background = '#fb923c'; b.style.color = '#000'; }
  else { b.textContent = 'NORMAL'; b.style.background = '#22c55e'; b.style.color = '#000'; }
  document.getElementById('cardSrc').className = 'sw-card' + (d.src ? ' on-src' : '');
  document.getElementById('pillSrc').textContent = d.src ? 'ACTIVE' : 'OFF';
  document.getElementById('cardFlt').className = 'sw-card' + (d.flt ? ' on-flt' : '');
  document.getElementById('pillFlt').textContent = d.flt ? 'FAULT ON' : 'OFF';
  document.getElementById('cardDaes').className = 'sw-card' + (d.daes ? ' on-daes' : '');
  document.getElementById('pillDaes').textContent = d.daes ? 'DAES ON' : 'FIXED';
}
async function toggleSw(sw) { try { const r = await fetch('/toggle?sw=' + sw); render(await r.json()); } catch (e) {} }
async function poll() { try { const r = await fetch('/status'); render(await r.json()); } catch (e) {} }
setInterval(poll, 900); poll();
</script>
</body>
</html>
)rawliteral";

void sendStatusJson() {
  bool injSrc = (digitalRead(PIN_SW_SOURCE) == LOW) || serSrc;
  bool injFlt = (digitalRead(PIN_SW_FAULT) == LOW) || serFlt;
  bool daesOn = (digitalRead(PIN_SW_MODE) == LOW) ? false : serDaes;
  char buf[220];
  snprintf(buf, sizeof(buf),
    "{\"sample\":%lu,\"src\":%s,\"flt\":%s,\"daes\":%s,\"gate\":%d,\"alarm\":%s,\"m2\":%.2f,\"alpha\":%.3f,\"eig\":%.2f}",
    (unsigned long)sampleIdx,
    injSrc ? "true" : "false",
    injFlt ? "true" : "false",
    daesOn ? "true" : "false",
    lastGate,
    lastAlarm ? "true" : "false",
    lastM2,
    alpha,
    lambdaMax
  );
  server.send(200, "application/json", buf);
}

// ==================== MATH & DAES CORE ====================
float u01() { return (float)random(1, 1000000) / 1000000.0f; }
int poisson(float lam) {
  if (lam <= 0.0f) return 0;
  if (lam < 30.0f) {
    float L = expf(-lam), p = 1.0f; int k = 0;
    do { k++; p *= u01(); } while (p > L);
    return k - 1;
  }
  float z = sqrtf(-2.0f * logf(u01())) * cosf(2.0f * PI * u01());
  float v = lam + sqrtf(lam) * z + 0.5f;
  return (v < 0.0f) ? 0 : (int)v;
}

float mahalanobis2(const float obs[NUM_W]) {
  float A[NUM_W][NUM_W + 1], diff[NUM_W];
  for (int i = 0; i < NUM_W; i++) {
    diff[i] = obs[i] - mu[i];
    for (int j = 0; j < NUM_W; j++) A[i][j] = cov[i][j] + (i == j ? SHRINK : 0.0f);
    A[i][NUM_W] = diff[i];
  }
  for (int i = 0; i < NUM_W; i++) {
    int piv = i;
    for (int r = i + 1; r < NUM_W; r++) if (fabsf(A[r][i]) > fabsf(A[piv][i])) piv = r;
    for (int c = 0; c <= NUM_W; c++) { float t = A[i][c]; A[i][c] = A[piv][c]; A[piv][c] = t; }
    float d = fabsf(A[i][i]) < 1e-4f ? 1e-4f : A[i][i];
    for (int c = i; c <= NUM_W; c++) A[i][c] /= d;
    for (int r = 0; r < NUM_W; r++) if (r != i) {
      float f = A[r][i];
      for (int c = i; c <= NUM_W; c++) A[r][c] -= f * A[i][c];
    }
  }
  float m2 = 0.0f;
  for (int i = 0; i < NUM_W; i++) m2 += diff[i] * A[i][NUM_W];
  return m2 < 0.0f ? 0.0f : m2;
}

void updateDAES(const float obs[NUM_W], bool useDaes) {
  for (int it = 0; it < 2; it++) {
    float nv[NUM_W] = {0}, n2 = 0.0f;
    for (int i = 0; i < NUM_W; i++) {
      for (int j = 0; j < NUM_W; j++) nv[i] += cov[i][j] * eigVec[j];
      n2 += nv[i] * nv[i];
    }
    float inv = n2 > 1e-6f ? 1.0f / sqrtf(n2) : 1.0f;
    for (int i = 0; i < NUM_W; i++) eigVec[i] = nv[i] * inv;
  }
  float rq = 0.0f, tr = 0.0f;
  for (int i = 0; i < NUM_W; i++) {
    float cv = 0.0f;
    for (int j = 0; j < NUM_W; j++) cv += cov[i][j] * eigVec[j];
    rq += eigVec[i] * cv; tr += mu[i];
  }
  lambdaMax = rq > 0.1f ? rq : 0.1f;
  float expVar = (tr / NUM_W) * 2.2f + SHRINK;
  float ratio = lambdaMax / (expVar > 1.0f ? expVar : 1.0f);
  alpha = useDaes ? constrain(0.02f + 0.06f * (ratio - 1.0f), 0.02f, 0.28f) : 0.08f;

  float res[NUM_W];
  for (int i = 0; i < NUM_W; i++) { res[i] = obs[i] - mu[i]; mu[i] += alpha * res[i]; }
  for (int i = 0; i < NUM_W; i++)
    for (int j = 0; j < NUM_W; j++)
      cov[i][j] = useDaes ? ((1.0f - alpha) * cov[i][j] + alpha * res[i] * res[j])
                          : (i == j ? 0.95f * cov[i][j] + 0.05f * res[i] * res[j] : cov[i][j] * 0.9f);
}

// ==================== CLEAR SELF-EXPLANATORY TFT UI ====================
void drawPill(int x, int y, int w, const char* txt, uint16_t fillCol, uint16_t txtCol) {
  tft.fillRoundRect(x, y, w, 11, 2, fillCol);
  tft.setTextColor(txtCol);
  tft.setCursor(x + 3, y + 2);
  tft.print(txt);
}

void drawDashboard(bool daesOn, bool injSrc, bool injFlt, int gate, bool alarm, float m2, float gross, const float obs[NUM_W]) {
  // 1. TOP STATUS BANNER (y = 0..15) — Plain-English System Verdict
  uint16_t bCol = alarm ? ST77XX_RED : (gate == 2 ? COL_ORANGE : (gate == 1 ? ST77XX_YELLOW : ST77XX_GREEN));
  uint16_t tCol = alarm ? ST77XX_WHITE : ST77XX_BLACK;
  tft.fillRect(0, 0, 160, 16, bCol);
  tft.setTextSize(1);
  tft.setTextColor(tCol);
  tft.setCursor(4, 4);
  if (alarm)          tft.print("!! RADIATION ALARM !!");
  else if (gate == 1) tft.print("FAULT | MODEL LOCKED");
  else if (gate == 2) tft.print("HOLD  | SOURCE GUARD");
  else                tft.print("SAFE  | LEARNING BG");

  // 2. ACTIVE SWITCH PILL ROW (y = 18..29) — Shows Mode, Source, Fault states
  tft.fillRect(0, 16, 160, 15, COL_BG_DARK);
  drawPill(2,   18, 52, daesOn ? "MD:DAES" : "MD:FIX",  daesOn ? ST77XX_CYAN : COL_CARD_BG, daesOn ? ST77XX_BLACK : COL_MUTED);
  drawPill(57,  18, 50, injSrc ? "SRC:ON"  : "SRC:OFF", injSrc ? ST77XX_RED  : COL_CARD_BG, injSrc ? ST77XX_WHITE : COL_MUTED);
  drawPill(110, 18, 48, injFlt ? "FLT:ON"  : "FLT:OFF", injFlt ? ST77XX_YELLOW : COL_CARD_BG, injFlt ? ST77XX_BLACK : COL_MUTED);

  // 3. PLAIN-ENGLISH TELEMETRY & THREAT GAUGE (y = 31..65)
  tft.fillRect(0, 31, 160, 35, ST77XX_BLACK);

  // Row A: Threat score (M2 vs 28 alarm limit) + visual gauge bar
  tft.setTextColor(COL_MUTED);
  tft.setCursor(3, 33);
  tft.print("THREAT:");
  tft.setTextColor(alarm ? ST77XX_RED : ST77XX_WHITE);
  tft.setCursor(47, 33);
  tft.printf("%4.1f/28", m2 > 999.9f ? 999.9f : m2);

  // Threat meter bar (x = 96..156, width = 60px, full scale = 35.0)
  tft.drawRect(96, 33, 60, 7, COL_MUTED);
  int fillW = constrain((int)((m2 / 35.0f) * 58.0f), 1, 58);
  uint16_t barCol = alarm ? ST77XX_RED : (m2 >= GATE_M2 ? COL_ORANGE : ST77XX_GREEN);
  tft.fillRect(97, 34, fillW, 5, barCol);
  // White tick mark at Alarm threshold (28 / 35 * 58 = 46px)
  tft.drawFastVLine(97 + 46, 32, 9, ST77XX_WHITE);

  // Row B: Adapt Speed (%) + Model Learning Status
  tft.setTextColor(COL_MUTED);
  tft.setCursor(3, 44);
  tft.print("ADAPT:");
  tft.setTextColor(ST77XX_CYAN);
  tft.setCursor(41, 44);
  tft.printf("%4.1f%%", alpha * 100.0f);

  tft.setTextColor(COL_MUTED);
  tft.setCursor(82, 44);
  tft.print("BG:");
  bool adapting = (gate == 0) || (!daesOn && gate == 2);
  tft.setTextColor(adapting ? ST77XX_GREEN : ST77XX_YELLOW);
  tft.setCursor(102, 44);
  tft.print(adapting ? "UPDATING" : "LOCKED");

  // Row C: Total Count Rate (CPS) + Drift Level
  tft.setTextColor(COL_MUTED);
  tft.setCursor(3, 55);
  tft.print("RATE:");
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(35, 55);
  tft.printf("%3.0fcps", gross);

  tft.setTextColor(COL_MUTED);
  tft.setCursor(82, 55);
  tft.print("DRIFT:");
  tft.setTextColor(ST77XX_WHITE);
  tft.setCursor(119, 55);
  tft.printf("%4.1f", lambdaMax);

  // 4. 6-WINDOW GAMMA SPECTRUM BARS (y = 66..127)
  tft.drawFastHLine(0, 66, 160, COL_CARD_BG);
  tft.fillRect(0, 67, 160, 61, ST77XX_BLACK);
  tft.setTextColor(COL_MUTED);
  tft.setCursor(3, 69);
  tft.print("SPECTRUM(WHITE=BG,BAR=NOW)");

  float mx = 25.0f;
  for (int i = 0; i < NUM_W; i++) {
    if (obs[i] > mx) mx = obs[i];
    if (mu[i] > mx) mx = mu[i];
  }
  for (int i = 0; i < NUM_W; i++) {
    int x = 6 + i * 25;
    int bh = constrain((int)((obs[i] / mx) * 38.0f), 2, 38);
    uint16_t col = (alarm && obs[i] > mu[i] * 1.45f) ? ST77XX_RED : (gate == 1 ? ST77XX_YELLOW : ST77XX_CYAN);
    tft.fillRect(x, 117 - bh, 20, bh, col);

    // Learned background reference line (White)
    int my = 117 - constrain((int)((mu[i] / mx) * 38.0f), 2, 38);
    tft.drawFastHLine(x - 1, my, 22, ST77XX_WHITE);

    // Channel label E1..E6
    tft.setTextColor(i == 3 && injSrc ? ST77XX_RED : ST77XX_WHITE);
    tft.setCursor(x + 4, 119);
    tft.printf("E%d", i + 1);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SW_SOURCE, INPUT_PULLUP);
  pinMode(PIN_SW_FAULT, INPUT_PULLUP);
  pinMode(PIN_SW_MODE, INPUT_PULLUP);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YEL, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  tft.initR(INITR_BLACKTAB);
  tft.setRotation(1);
  tft.fillScreen(ST77XX_BLACK);

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);

  server.on("/", HTTP_GET, []() { server.send_P(200, "text/html", INDEX_HTML); });
  server.on("/status", HTTP_GET, sendStatusJson);
  server.on("/toggle", HTTP_GET, []() {
    String sw = server.arg("sw");
    if (sw == "1") serSrc = !serSrc;
    else if (sw == "2") serFlt = !serFlt;
    else if (sw == "3") serDaes = !serDaes;
    else if (sw == "0") { serSrc = false; serFlt = false; serDaes = true; }
    sendStatusJson();
  });
  server.begin();

  float bg0 = 80.0f + ((float)analogRead(PIN_POT_BG) / 4095.0f) * 220.0f;
  for (int i = 0; i < NUM_W; i++) {
    mu[i] = bg0 * W_BASE[i];
    lastObs[i] = mu[i];
    eigVec[i] = 1.0f / sqrtf((float)NUM_W);
    for (int j = 0; j < NUM_W; j++) cov[i][j] = (i == j) ? (mu[i] + SHRINK) : 0.0f;
    for (int k = 0; k < FANO_LEN; k++) ring[i][k] = mu[i];
  }
  Serial.println("Type 1=Source, 2=Fault, 3=Toggle DAES/Static | Wi-Fi AP: SPECTRA-Control (http://192.168.4.1)");
}

void loop() {
  server.handleClient();

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '1') serSrc = !serSrc;
    if (c == '2') serFlt = !serFlt;
    if (c == '3') serDaes = !serDaes;
  }
  uint32_t now = millis();
  if (now - lastTick < 1000) return;
  uint32_t dt = now - lastTick;
  lastTick = now; sampleIdx++;

  float pBg = (float)analogRead(PIN_POT_BG) / 4095.0f;
  float pDr = (float)analogRead(PIN_POT_DRIFT) / 4095.0f;
  bool injSrc = (digitalRead(PIN_SW_SOURCE) == LOW) || serSrc;
  bool injFlt = (digitalRead(PIN_SW_FAULT) == LOW) || serFlt;
  bool daesOn = (digitalRead(PIN_SW_MODE) == LOW) ? false : serDaes;

  float gross = 80.0f + pBg * 240.0f;
  driftPhase += 0.08f + pDr * 0.22f;
  float drift = 1.0f + (0.35f * pDr) * sinf(driftPhase);

  float obs[NUM_W];
  for (int i = 0; i < NUM_W; i++) {
    float tilt = 1.0f + pDr * 0.18f * ((float)i - 2.5f) * cosf(driftPhase);
    float lam = gross * W_BASE[i] * drift * tilt + (injSrc ? SRC_ADD[i] : 0.0f);
    obs[i] = (float)poisson(lam);
  }
  if (injFlt) {
    if (sampleIdx % 8 < 5) for (int i = 0; i < NUM_W; i++) obs[i] = lastObs[i];
    else { obs[2] = 0.0f; dt = 1650; }
  } else for (int i = 0; i < NUM_W; i++) lastObs[i] = obs[i];

  int gate = 0;
  if (dt < 750 || dt > 1350) gate = 1;
  for (int i = 0; i < NUM_W; i++) ring[i][ringIdx] = obs[i];
  ringIdx = (ringIdx + 1) % FANO_LEN;
  if (ringCnt < FANO_LEN) ringCnt++;
  if (gate == 0 && ringCnt >= 6) {
    for (int i = 0; i < NUM_W; i++) {
      float s = 0, vs = 0;
      for (int k = 0; k < ringCnt; k++) s += ring[i][k];
      float mn = s / ringCnt;
      for (int k = 0; k < ringCnt; k++) vs += (ring[i][k] - mn) * (ring[i][k] - mn);
      float fano = mn > 1.0f ? (vs / (ringCnt - 1)) / mn : 1.0f;
      if (fano < 0.25f || fano > 4.20f) gate = 1;
    }
  }

  float m2 = mahalanobis2(obs);
  bool alarm = (gate == 0) && (m2 >= ALARM_M2);
  if (gate == 0 && m2 >= GATE_M2) gate = 2;

  if (gate == 0) updateDAES(obs, daesOn);
  else if (!daesOn && gate == 2) updateDAES(obs, false);

  lastM2 = m2; lastGross = gross; lastGate = gate; lastAlarm = alarm;

  digitalWrite(PIN_LED_GREEN, (gate == 0 && !alarm));
  digitalWrite(PIN_LED_YEL,   (gate == 1));
  digitalWrite(PIN_LED_RED,   alarm);
  digitalWrite(PIN_BUZZER,    alarm ? HIGH : LOW);

  drawDashboard(daesOn, injSrc, injFlt, gate, alarm, m2, gross, obs);

  Serial.printf(
    "DATA,%lu,%lu,%lu,%d,%d,%d,%d,%.2f,%.2f,%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f\n",
    (unsigned long)sampleIdx,
    (unsigned long)now,
    (unsigned long)dt,
    daesOn ? 1 : 0,
    injSrc ? 1 : 0,
    injFlt ? 1 : 0,
    gate,
    m2,
    lambdaMax,
    alpha,
    gross,
    obs[0],
    obs[1],
    obs[2],
    obs[3],
    obs[4],
    obs[5]
  );
}