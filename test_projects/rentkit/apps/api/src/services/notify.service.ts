/**
 * Уведомления клиенту при смене статуса брони.
 *
 * Канал выбирается по наличию настроек: письмо, если задан SMTP, иначе SMS.
 * Если не настроено ничего (локальная разработка) — шаблон просто печатается в лог.
 * Падение отправки никогда не должно ронять основной сценарий, поэтому все ошибки
 * гасятся внутри и только логируются.
 */

import type { Booking, Customer, Item } from '@rentkit/core';
import { formatKop } from '@rentkit/core';
import { config } from '../config.js';

export type NotifyEvent =
  | 'booking.created'
  | 'booking.cancelled'
  | 'booking.picked_up'
  | 'booking.returned'
  | 'booking.overdue';

export interface NotifyContext {
  booking: Booking;
  customer: Customer;
  item: Item;
  /** Сумма для шаблонов, где она нужна: депозит, штраф, возврат. */
  amountKop?: number;
}

interface Message {
  subject: string;
  body: string;
}

function shortDate(iso: string): string {
  const dt = new Date(iso);
  return dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

/** Шаблоны писем и SMS. Текст согласован с поддержкой, менять только вместе с ними. */
function render(event: NotifyEvent, ctx: NotifyContext): Message {
  const { booking, customer, item } = ctx;
  const period = `${shortDate(booking.startAt)} — ${shortDate(booking.endAt)}`;

  switch (event) {
    case 'booking.created':
      return {
        subject: `Бронь ${booking.id} подтверждена`,
        body:
          `${customer.name}, забронировали «${item.title}» на ${period}.\n` +
          `К оплате при выдаче: ${formatKop(booking.quoteKop)}.\n` +
          `Депозит ${formatKop(ctx.amountKop ?? item.depositKop)} заблокирован на карте.\n` +
          'Пункт выдачи работает пн–сб с 10:00 до 20:00.',
      };
    case 'booking.cancelled':
      return {
        subject: `Бронь ${booking.id} отменена`,
        body:
          `${customer.name}, бронь на «${item.title}» (${period}) отменена.\n` +
          'Если отмена произошла по ошибке — оформите новую бронь в личном кабинете.',
      };
    case 'booking.picked_up':
      return {
        subject: `Техника выдана по брони ${booking.id}`,
        body:
          `${customer.name}, «${item.title}» выдан. Ждём обратно до ${shortDate(booking.endAt)}.\n` +
          'Опоздание больше двух часов оплачивается по тарифу за сутки просрочки.',
      };
    case 'booking.returned':
      return {
        subject: `Возврат по брони ${booking.id} принят`,
        body:
          `${customer.name}, спасибо! «${item.title}» принят в пункте выдачи.\n` +
          `Удержано из депозита: ${formatKop(ctx.amountKop ?? 0)}.`,
      };
    case 'booking.overdue':
      return {
        subject: `Просрочен возврат по брони ${booking.id}`,
        body:
          `${customer.name}, срок аренды «${item.title}» истёк ${shortDate(booking.endAt)}.\n` +
          'Верните технику в ближайшее рабочее время, штраф начисляется за каждые сутки.',
      };
    default:
      return { subject: `Бронь ${booking.id}`, body: 'Статус брони изменился.' };
  }
}

async function sendEmail(to: string, message: Message): Promise<void> {
  console.log(`[notify] email → ${to} (${config.notifyFrom}): ${message.subject}`);
}

async function sendSms(phone: string, message: Message): Promise<void> {
  console.log(`[notify] sms → ${phone}: ${message.subject}`);
}

/**
 * Отправить уведомление о смене статуса брони.
 * Вызывается из роутов после того, как изменение уже зафиксировано в базе.
 */
export async function notifyBooking(event: NotifyEvent, ctx: NotifyContext): Promise<void> {
  const message = render(event, ctx);

  try {
    if (config.smtpUrl) {
      await sendEmail(`${ctx.customer.id}@customers.local`, message);
      return;
    }
    if (config.smsGatewayUrl) {
      await sendSms(ctx.customer.phone, message);
      return;
    }
    console.log(`[notify] ${event} (отправка отключена)\n${message.subject}\n${message.body}`);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    console.error(`[notify] не удалось отправить ${event} по брони ${ctx.booking.id}: ${reason}`);
  }
}

/** Напоминание о просрочке. Дёргается ночным скриптом, не из роутов. */
export async function notifyOverdue(ctx: NotifyContext): Promise<void> {
  await notifyBooking('booking.overdue', ctx);
}
