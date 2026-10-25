// «Экскурсия»: a guided story through the copper value chain of Bozshakol.
// The camera flies from the drill rig to the concentrate; every caption is
// rendered from the live Ditto twins at that moment, so the story changes
// with the scenario (a broken shovel, rain, a stopped crusher...).

export function createTour(ctx) {
  const { v, num, objs, flyTo, follow, select, posOf, catalog } = ctx;
  const pick = (kind, pred) => catalog().filter((c) => c.kind === kind).map((c) => ({ id: c.id, t: ctx.twin(c.id) })).filter((x) => x.t && pred(x.t));
  const up = (id) => id.toUpperCase();
  const pct = (x, n = 1) => `${num(x, n)} %`;

  const STEPS = [
    {
      title: 'ГОК «Бозшаколь» — живой цифровой двойник',
      focus: () => ({ view: 'overview' }),
      text: () => `Модельное время ${v('site', 'sim_time', '—')}, смена ${v('site', 'shift', '—')}. Фабрика перерабатывает <b>${num(v('sag-01', 'throughput'))} т/ч</b> руды с <b>${num(v('site', 'feed_grade'), 3)} % Cu</b> и выпускает <b>${num(v('site', 'cu_tph'), 2)} т меди в час</b> — ${num(v('site', 'cu_plan_pct'))} % плана смены. Всё, что вы видите, — 113 двойников Eclipse Ditto.`,
    },
    {
      title: '1 · Бурение: MWD уточняет геологию',
      focus: () => {
        const d = pick('drill', (t) => t.state === 'drilling')[0] || pick('drill', () => true)[0];
        return d && { id: d.id, dist: 320, theta: 0.6, phi: 0.95 };
      },
      text: (f) => {
        const id = f?.id || 'dr-01';
        return `Станок <b>${up(id)}</b> (Sandvik D55SP) — ${v(id, 'state_ru', '')}: блок ${v(id, 'block', '—')}, скорость бурения <b>${num(v(id, 'rop'))} м/ч</b>, крепость по MWD <b>${num(v(id, 'ucs_est'))} МПа</b>. Оценка записывается в двойник блока и меняет сетку скважин и расход ВВ.`;
      },
    },
    {
      title: '2 · Взрывной блок и Mine-to-Mill',
      focus: () => {
        const b = pick('block', (t) => ['charged', 'charging'].includes(t.state))[0] || pick('block', (t) => ['drilled', 'drilling'].includes(t.state))[0];
        return b && { id: b.id, dist: 420, theta: -0.4, phi: 0.85 };
      },
      text: (f) => {
        const id = f?.id || 'blk-01';
        return `Блок <b>${v(id, 'code', '')}</b> — ${v(id, 'state_ru', '')}: заряжено ${num(v(id, 'holes_charged'))} из ${num(v(id, 'holes_total'))} скважин, ${num(v(id, 'powder_factor'), 2)} кг/м³. По Kuz-Ram ожидаемый кусок x80 <b>${num(v(id, 'x80', 0) || v('drill-blast', 'm2m_x80_cm', 0), 0)} см</b>: от него зависят скорость экскавации, ККД и энергия МПСИ. Следующее окно взрыва — ${v('drill-blast', 'next_window', '—')}.`;
      },
    },
    {
      title: '3 · Экскавация: качество из забоя',
      focus: () => {
        const l = pick('loader', (t) => t.state === 'loading').sort((a, b) => (b.t.block_grade || 0) - (a.t.block_grade || 0))[0] || pick('loader', () => true)[0];
        return l && { id: l.id, dist: 300, theta: 0.9, phi: 0.9 };
      },
      text: (f) => {
        const id = f?.id || 'sh-01';
        return `<b>${up(id)}</b> — ${v(id, 'state_ru', '')}: ${v(id, 'material', '')} с содержанием <b>${num(v(id, 'block_grade'), 2)} % Cu</b>, загрузка ${pct(v(id, 'utilization'), 0)}, в очереди ${num(v(id, 'queue'))} самосв. Диспетчер шихтует забои так, чтобы держать питание фабрики в коридоре 0,42 ± 0,03 % Cu.`;
      },
    },
    {
      title: '4 · Откатка: каждый рейс — партия руды',
      focus: () => {
        const t = pick('haul-truck', (x) => x.state === 'hauling' && (x.payload || 0) > 50 && /ККД/.test(x.destination || ''))[0]
          || pick('haul-truck', (x) => x.state === 'hauling')[0] || pick('haul-truck', () => true)[0];
        return t && { id: t.id, dist: 230, theta: -1.2, phi: 1.0, follow: true };
      },
      text: (f) => {
        const id = f?.id || 'ht-01';
        return `Самосвал <b>${up(id)}</b> везёт <b>${num(v(id, 'payload'))} т</b> (${num(v(id, 'load_grade'), 2)} % Cu) → ${v(id, 'destination', '—')}, <b>${num(v(id, 'speed'))} км/ч</b>. Скорость считается из тяговой мощности, уклона и сопротивления качению; топливо — ${num(v(id, 'fuel_lph'))} л/ч. На линии ${num(v('site', 'trucks_working'))} из ${num(v('haulage', 'trucks_total'))} машин.`;
      },
    },
    {
      title: '5 · ККД-1: первое узкое место',
      focus: () => ({ id: 'gc-01', dist: 380, theta: 0.7, phi: 0.9 }),
      text: () => `Гирационная дробилка: <b>${num(v('gc-01', 'throughput'))} т/ч</b>, в бункере ${num(v('gc-01', 'pocket_t'))} т, у бункера ${num(v('gc-01', 'trucks_queued'))} самосв. Износ брони <b>${num(v('gc-01', 'mantle_wear'))} %</b> — при 100 % двойник останавливает ККД на замену, и руда уходит на склад забаланса.`,
    },
    {
      title: '6 · Конвейер и склад крупного дробления',
      focus: () => ({ id: 'cos-01', dist: 900, theta: -0.9, phi: 0.95 }),
      text: () => `Конвейер 2,1 км несёт <b>${num(v('cv-01', 'load_tph'))} т/ч</b> (${num(v('cv-01', 'on_belt_t'))} т на ленте). Склад КД — <b>${num(v('cos-01', 'level_kt'), 1)} кт</b>, это ${num(v('cos-01', 'hours_cover'), 1)} ч работы фабрики: буфер между решениями диспетчера и МПСИ.`,
    },
    {
      title: '7 · Измельчение: главный потребитель энергии',
      focus: () => ({ id: 'sag-01', dist: 330, theta: -0.5, phi: 0.9 }),
      text: () => `МПСИ: <b>${num(v('sag-01', 'power_mw'), 1)} МВт</b>, ${num(v('sag-01', 'specific_energy'), 1)} кВт·ч/т — энергия растёт с крепостью, глиной и крупностью F80 ${num(v('cos-01', 'f80'))} мм. Шаровые мельницы доводят помол до <b>P80 ${num(v('bm-01', 'p80'))} мкм</b>. Нагрузка подстанции ${num(v('ss-220', 'total_mw'), 1)} МВт.`,
    },
    {
      title: '8 · Флотация: где теряется медь',
      focus: () => ({ id: 'fl-r', dist: 300, theta: 0.5, phi: 0.85 }),
      text: () => `Извлечение <b>${num(v('fl-r', 'recovery'), 1)} %</b> при глине в питании ${num(v('fl-r', 'feed_clay'), 1)} % и времени флотации ${num(v('fl-r', 'residence_min'), 1)} мин. Концентрат — <b>${num(v('fl-c', 'conc_grade'), 1)} % Cu</b>, ${num(v('fl-c', 'conc_tph'), 1)} т/ч. Глина из забоя здесь снижает выход меди: поэтому двойник сквозной.`,
    },
    {
      title: '9 · Реальные данные и ML',
      focus: () => ({ id: 'qc-01', dist: 260, theta: 0.9, phi: 1.0 }),
      text: () => `Анализатор <b>QC-01</b> проигрывает реальную флотационную фабрику (Kaggle, ${v('qc-01', 'record_time', '—')}). Анализ лаборатории приходит через 3 ч, а ML-софтсенсор оценивает SiO₂ в концентрате <b>сейчас: ${num(v('qc-01', 'silica_ml'), 2)} %</b> (факт ${num(v('qc-01', 'silica_actual'), 2)} %). На отложенных данных R² ${num(v('qc-01', 'model_r2'), 2)} против ${num(v('qc-01', 'naive_r2'), 2)} у последнего пришедшего анализа. Геология блоков взята из 2000 проб GeoMet через ML-сетку, крепость — из ML по химии.`,
    },
    {
      title: '10 · Контроль по ГОСТ: пробы, анализы, электроэнергия',
      focus: () => ({ id: 'lab-01', dist: 420, theta: 0.6, phi: 1.0 }),
      text: () => `Лаборатория <b>ОТК</b> опробует смену по ГОСТ 14180-80: ${num(v('lab-01', 'n_points'))} точечных проб по ${num(v('lab-01', 'm_point'), 1)} кг каждые ${num(v('lab-01', 'period_min'), 0)} мин (V ${num(v('lab-01', 'v_cu'), 1)} %). Баланс по трём продуктам: ε <b>${num(v('lab-01', 'eps_lab'), 1)} %</b> против ${num(v('lab-01', 'eps_plant'), 1)} % по фабрике; влага концентрата ${num(v('lab-01', 'w_conc'), 1)} % (ГОСТ 13170), класс −0,08 мм ${num(v('lab-01', 'sieve_minus_008'), 1)} % (ГОСТ 24598). Электроэнергия на ПС 220 кВ — по ГОСТ 32144: K_U <b>${num(v('pq-01', 'ku'), 2)} %</b> (норма 2 %), ${v('pq-01', 'compliance', 'оценка накапливается')}.`,
    },
    {
      title: '11 · Хвосты и вода',
      focus: () => ({ id: 'tsf-01', dist: 1500, theta: -0.3, phi: 0.95 }),
      text: () => `В хвостах остаётся ${num(v('fl-r', 'tails_grade'), 3)} % Cu. Хвостохранилище — ${num(v('tsf-01', 'volume_mm3'), 1)} млн м³, запас высоты дамбы ${num(v('tsf-01', 'freeboard'), 1)} м; оборотная вода ${num(v('tsf-01', 'reclaim_m3h'))} м³/ч, свежая — ${num(v('water-01', 'fresh_m3h'))} м³/ч из канала им. Сатпаева.`,
    },
    {
      title: '12 · Безопасность: борта, люди, сейсмика',
      focus: () => ({ id: 'sr-01', dist: 1300, theta: 2.6, phi: 0.9, target: 'pit' }),
      text: () => `Радар SR-01: скорость смещения W1 ${num(v('sr-01', 'w1_velocity'), 1)}, W2 ${num(v('sr-01', 'w2_velocity'), 1)}, W3 ${num(v('sr-01', 'w3_velocity'), 1)} мм/сут (пороги 5 и 15). Дождь поднимает поровое давление — на жёлтом уровне скорость на съезде ограничивается, на красном работы под бортом запрещены. В карьере ${num(v('safety', 'people_in_pit'))} чел., CAS за смену: ${num(v('safety', 'cas_alerts_shift'))}. Сейсмостанция SM-01 (реальные данные UCI): ML-вероятность опасной смены ${num(v('sm-01', 'hazard_ml'), 0)} %.`,
    },
    {
      title: '13 · «Что если»: решение до того, как оно принято',
      focus: () => ({ view: 'overview' }),
      text: () => {
        const sc = v('whatif', 'scenario', 'базовый режим');
        const dm = v('whatif', 'delta_margin_mkzt'), dc = v('whatif', 'delta_cu_t');
        const tail = dm === undefined ? '' : ` Прогноз на 48 ч: маржа ${dm > 0 ? '+' : ''}${num(dm, 1)} %, медь ${dc > 0 ? '+' : ''}${num(dc, 1)} %.`;
        return `Активный сценарий: <b>${sc}</b>.${tail} Выберите сценарий слева — ливень, отказ экскаватора, остановку ККД — и двойник прогонит две копии рудника на 48 ч на одинаковых случайных числах. Последствия появятся прямо на сцене: столбики «база / сценарий» над складами, экскаваторами, мельницей и парком с ползунком по 48 часам.`;
      },
    },
  ];

  const el = document.getElementById('tour');
  const tTitle = el.querySelector('.tour-title'), tText = el.querySelector('.tour-text'), tDots = el.querySelector('.tour-dots');
  const STEP_MS = 11000;
  let idx = -1, timer = null, focus = null, running = false, textTimer = null;

  tDots.innerHTML = STEPS.map((_, i) => `<i data-i="${i}"></i>`).join('');
  tDots.querySelectorAll('i').forEach((d) => d.addEventListener('click', () => go(+d.dataset.i)));
  el.querySelector('.tour-prev').addEventListener('click', () => go((idx - 1 + STEPS.length) % STEPS.length));
  el.querySelector('.tour-next').addEventListener('click', () => go((idx + 1) % STEPS.length));
  el.querySelector('.tour-close').addEventListener('click', () => stop());

  function render() {
    const s = STEPS[idx];
    if (!s) return;
    tTitle.textContent = s.title;
    tText.innerHTML = s.text(focus);
  }
  function go(i) {
    idx = i;
    const s = STEPS[idx];
    focus = s.focus() || { view: 'overview' };
    follow(false);
    if (focus.view) flyTo(focus.view);
    else {
      const fly = (tries) => {
        const p = focus.target === 'pit' ? posOf('pit') : posOf(focus.id);
        if (p) flyTo({ t: p, dist: focus.dist, theta: focus.theta, phi: focus.phi }, 2200);
        else if (tries > 0) setTimeout(() => { if (STEPS[idx] === s) fly(tries - 1); }, 500);
      };
      fly(10);
      if (focus.id) select(focus.id, true);
      if (focus.follow) setTimeout(() => { if (running && STEPS[idx] === s) follow(true); }, 2300);
    }
    tDots.querySelectorAll('i').forEach((d, k) => d.classList.toggle('on', k === idx));
    el.classList.remove('fade'); void el.offsetWidth; el.classList.add('fade');
    render();
    clearTimeout(timer);
    if (running) timer = setTimeout(() => go((idx + 1) % STEPS.length), STEP_MS);
  }
  function start(from = 0) {
    running = true;
    el.classList.remove('hidden');
    document.getElementById('tourBtn')?.classList.add('active');
    clearInterval(textTimer); textTimer = setInterval(render, 2000);
    go(from);
  }
  function stop() {
    running = false;
    clearTimeout(timer); clearInterval(textTimer);
    el.classList.add('hidden');
    follow(false);
    document.getElementById('tourBtn')?.classList.remove('active');
  }
  // Any manual camera move pauses the auto-advance (the caption stays).
  function userInterrupt() { if (running) { clearTimeout(timer); timer = setTimeout(() => go((idx + 1) % STEPS.length), STEP_MS * 2); } }
  return { start, stop, userInterrupt, get running() { return running; }, steps: STEPS.length };
}
