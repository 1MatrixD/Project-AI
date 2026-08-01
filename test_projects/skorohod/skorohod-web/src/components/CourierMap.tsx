'use client';

import { useEffect, useRef } from 'react';
import clsx from 'clsx';
import type { Courier } from '@/types';

/**
 * Заглушка карты: рисуем на canvas сетку кварталов, точку курьера и точку
 * адреса доставки. Полноценные тайлы подключим отдельной задачей — пока
 * лицензия на картографию не куплена, внешние библиотеки не тянем.
 */

interface Props {
  courier: Courier | null;
  /** Координаты адреса доставки; если их нет — центрируемся на курьере. */
  destination?: { lat: number; lon: number };
  className?: string;
}

const W = 560;
const H = 280;
/** Сколько градусов широты/долготы влезает в кадр. */
const SPAN = 0.02;

export default function CourierMap({ courier, destination, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = '#f3f4f6';
    ctx.fillRect(0, 0, W, H);

    // Сетка «кварталов» — чисто декоративная.
    ctx.strokeStyle = '#e2e4e8';
    ctx.lineWidth = 1;
    for (let x = 0; x <= W; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, H);
      ctx.stroke();
    }
    for (let y = 0; y <= H; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(W, y + 0.5);
      ctx.stroke();
    }

    if (!courier) return;

    const center = destination ?? { lat: courier.lat, lon: courier.lon };
    const project = (lat: number, lon: number): [number, number] => {
      const x = W / 2 + ((lon - center.lon) / SPAN) * W;
      const y = H / 2 - ((lat - center.lat) / SPAN) * H;
      return [x, y];
    };

    const [cx, cy] = project(courier.lat, courier.lon);

    if (destination) {
      const [dx, dy] = project(destination.lat, destination.lon);
      ctx.strokeStyle = '#f97316';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 5]);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(dx, dy);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#16181d';
      ctx.beginPath();
      ctx.arc(dx, dy, 5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Курьер — оранжевый маркер с белой обводкой.
    ctx.fillStyle = '#f97316';
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 3;
    ctx.stroke();
  }, [courier, destination]);

  return (
    <div className={clsx('skh-card overflow-hidden', className)}>
      <canvas
        ref={canvasRef}
        style={{ width: W, height: H }}
        className="block max-w-full"
        role="img"
        aria-label={courier ? `Курьер ${courier.name} на карте` : 'Курьер ещё не назначен'}
      />
      <div className="flex items-center justify-between px-4 py-2.5 text-xs text-ink-400">
        {courier ? (
          <>
            <span className="text-ink-600">{courier.name}</span>
            <span className="tabular-nums">
              {courier.lat.toFixed(5)}, {courier.lon.toFixed(5)}
            </span>
          </>
        ) : (
          <span>Курьер ещё не назначен</span>
        )}
      </div>
    </div>
  );
}
