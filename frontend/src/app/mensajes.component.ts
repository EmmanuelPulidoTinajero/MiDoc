import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  ApiService,
  Appointment,
  ChatMessage,
  Consent,
  Conversation,
  Patient,
  errorMessage,
  formatDateTime,
} from './api.service';
import {
  DsAlertBannerComponent,
  DsBadgeComponent,
  DsButtonComponent,
  DsCardComponent,
  DsControlDirective,
  DsEmptyStateComponent,
  DsFieldComponent,
  DsPageHeaderComponent,
  DsSkeletonComponent,
} from './ds';

/** Mensajes privados entre paciente y profesional con cita o consentimiento previo. */
@Component({
  selector: 'midoc-mensajes',
  standalone: true,
  imports: [
    FormsModule,
    DsAlertBannerComponent,
    DsBadgeComponent,
    DsButtonComponent,
    DsCardComponent,
    DsControlDirective,
    DsEmptyStateComponent,
    DsFieldComponent,
    DsPageHeaderComponent,
    DsSkeletonComponent,
  ],
  template: `
    <ds-card padding="lg">
      <ds-page-header
        eyebrow="Comunicación clínica"
        title="Mensajes privados"
        subtitle="Conversa de forma directa con tus contactos autorizados. No utilices este canal para emergencias médicas."
        [headingLevel]="2"
      >
        <div dsPageActions>
          <ds-button variant="secondary" size="sm" [loading]="loadingContacts()" (pressed)="load()">
            Actualizar
          </ds-button>
        </div>
      </ds-page-header>

      @if (subscriptionRequired()) {
        <ds-empty-state
          icon="message"
          title="Activa tu suscripción para usar mensajes"
          description="Tu cuenta profesional requiere una suscripción activa para iniciar o responder conversaciones con pacientes."
          actionLabel="Ir a suscripción"
          (action)="goToSubscription()"
        />
      } @else if (loadingContacts()) {
        <ds-skeleton variant="card" [count]="2" label="Cargando conversaciones" />
      } @else if (loadError()) {
        <ds-alert-banner
          tone="danger"
          [message]="loadError()"
          actionLabel="Reintentar"
          (action)="load()"
        />
      } @else if (contacts().length === 0) {
        <ds-empty-state
          icon="message"
          title="Todavía no tienes conversaciones"
          [description]="
            api.isDoctor()
              ? 'Tus pacientes aparecerán aquí cuando te otorguen acceso a su expediente o agenden contigo.'
              : 'Podrás escribir a un profesional después de agendar una cita o darle acceso a tu expediente.'
          "
          [actionLabel]="api.isDoctor() ? 'Ver agenda' : 'Buscar profesionales'"
          (action)="openEmptyAction()"
        />
      } @else {
        <div class="chat-shell" [class.has-active-thread]="!!selectedContact()">
          <aside class="chat-sidebar" aria-label="Conversaciones disponibles">
            <ul class="chat-contacts">
              @for (contact of contacts(); track contact.userId) {
                <li>
                  <button
                    type="button"
                    class="chat-contact-btn"
                    [class.is-selected]="selectedContact()?.userId === contact.userId"
                    [attr.aria-current]="selectedContact()?.userId === contact.userId ? 'true' : null"
                    (click)="selectContact(contact)"
                  >
                    <div class="row" style="width: 100%;">
                      <strong>{{ contact.name }}</strong>
                      @if (contact.unread > 0) {
                        <ds-badge tone="warning">{{ contact.unread }}</ds-badge>
                      }
                    </div>
                    <span class="chat-snippet">
                      {{ contact.lastMessage || 'Sin mensajes todavía — inicia la conversación' }}
                    </span>
                    @if (contact.updatedAt) {
                      <time class="chat-time">{{ formatDateTime(contact.updatedAt) }}</time>
                    }
                  </button>
                </li>
              }
            </ul>
          </aside>

          <section class="chat-thread" aria-label="Hilo de mensajes">
            @if (selectedContact(); as active) {
              <div class="stack">
                <div class="row chat-thread-header">
                  <div class="row-start">
                    <ds-button
                      class="mobile-back"
                      variant="ghost"
                      size="sm"
                      (pressed)="clearSelection()"
                    >
                      ← Conversaciones
                    </ds-button>
                    <h3 style="margin: 0;">{{ active.name }}</h3>
                  </div>
                  <ds-button
                    variant="ghost"
                    size="sm"
                    [loading]="loadingThread()"
                    (pressed)="loadConversation()"
                  >
                    Recargar hilo
                  </ds-button>
                </div>

                @if (message()) {
                  <ds-alert-banner [tone]="messageTone()" [message]="message()" />
                }

                @if (loadingThread()) {
                  <ds-skeleton variant="row" [count]="3" label="Cargando mensajes" />
                } @else {
                  <ol
                    id="chat-scroll-box"
                    class="message-list"
                    aria-label="Mensajes de esta conversación"
                    aria-live="polite"
                  >
                    @for (item of messages(); track item.id) {
                      <li [class.own-message]="item.senderId === api.user()?.id">
                        <p>{{ item.content }}</p>
                        <time>
                          {{ item.senderId === api.user()?.id ? 'Tú · ' : '' }}{{ formatDateTime(item.createdAt) }}
                        </time>
                      </li>
                    } @empty {
                      <li>
                        <p class="muted" style="margin: 0;">Aún no hay mensajes. Escribe abajo para iniciar la conversación.</p>
                      </li>
                    }
                  </ol>
                }

                <form class="stack" (ngSubmit)="send()">
                  <ds-field
                    label="Escribe tu mensaje"
                    [hint]="content.length + ' / 2000 caracteres'"
                  >
                    <textarea
                      dsControl
                      name="content"
                      [(ngModel)]="content"
                      maxlength="2000"
                      rows="3"
                      [disabled]="sending()"
                    ></textarea>
                  </ds-field>
                  <div class="row-start">
                    <ds-button
                      type="submit"
                      variant="primary"
                      [disabled]="!content.trim()"
                      [loading]="sending()"
                    >
                      {{ sending() ? 'Enviando…' : 'Enviar mensaje' }}
                    </ds-button>
                  </div>
                </form>
              </div>
            } @else {
              <ds-empty-state
                icon="message"
                title="Selecciona una conversación"
                description="Elige un contacto de la lista para leer los mensajes y responder."
              />
            }
          </section>
        </div>
      }
    </ds-card>
  `,
  styles: `
    .chat-shell {
      display: grid;
      grid-template-columns: minmax(15rem, 20rem) minmax(0, 1fr);
      gap: var(--space-4);
      align-items: start;
    }

    .chat-sidebar,
    .chat-thread {
      min-width: 0;
    }

    .chat-contacts {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-2);
    }

    .chat-contact-btn {
      display: grid;
      gap: var(--space-1);
      width: 100%;
      text-align: left;
      padding: var(--space-3);
      border: 1px solid var(--color-border-strong);
      border-radius: var(--radius-md);
      background: var(--color-surface);
      color: var(--color-text);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      cursor: pointer;
      transition: background-color var(--motion-fast) var(--ease-standard);
    }

    .chat-contact-btn:hover {
      background: var(--color-surface-muted);
    }

    .chat-contact-btn.is-selected {
      background: var(--color-primary-soft);
      border-color: var(--color-primary);
    }

    .chat-snippet {
      color: var(--color-text-soft);
      font-size: var(--text-xs);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .chat-time {
      color: var(--color-text-soft);
      font-size: var(--text-xs);
    }

    .chat-thread-header {
      padding-bottom: var(--space-2);
      border-bottom: 1px solid var(--color-border);
    }

    .mobile-back {
      display: none;
    }

    @media (max-width: 640px) {
      .chat-shell {
        grid-template-columns: minmax(0, 1fr);
      }

      .chat-shell.has-active-thread .chat-sidebar {
        display: none;
      }

      .chat-shell:not(.has-active-thread) .chat-thread {
        display: none;
      }

      .mobile-back {
        display: inline-block;
      }
    }
  `,
})
export class MensajesComponent implements OnInit {
  readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly contacts = signal<Conversation[]>([]);
  readonly selectedContact = signal<Conversation | null>(null);
  readonly messages = signal<ChatMessage[]>([]);
  readonly loadingContacts = signal(true);
  readonly loadingThread = signal(false);
  readonly subscriptionRequired = signal(false);
  readonly loadError = signal('');
  readonly message = signal('');
  readonly messageTone = signal<'info' | 'success' | 'danger'>('info');
  readonly sending = signal(false);
  readonly formatDateTime = formatDateTime;

  content = '';

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    this.loadingContacts.set(true);
    this.loadError.set('');
    this.subscriptionRequired.set(false);
    try {
      const threads = await this.api.get<Conversation[]>('/api/messages');
      const known = new Map<string, Conversation>(threads.map((thread) => [thread.userId, thread]));

      if (this.api.isDoctor()) {
        const patients = await this.api.get<Patient[]>('/api/doctor/patients');
        for (const patient of patients) {
          known.set(
            patient.patientId,
            known.get(patient.patientId) ?? {
              userId: patient.patientId,
              name: patient.name || patient.email,
              lastMessage: '',
              updatedAt: patient.accessSince,
              unread: 0,
            },
          );
        }
      } else {
        const [consents, appointments] = await Promise.all([
          this.api.get<Consent[]>('/api/consents'),
          this.api.get<Appointment[]>('/api/appointments'),
        ]);
        const doctorIds = new Set<string>();
        for (const c of consents) {
          if (c.granted) doctorIds.add(c.doctorId);
        }
        for (const a of appointments) {
          if (a.doctorId) doctorIds.add(a.doctorId);
        }

        if (doctorIds.size > 0) {
          const settled = await Promise.allSettled(
            [...doctorIds].map((id) => this.api.resolveDoctorUserId(id)),
          );
          for (const outcome of settled) {
            if (outcome.status === 'fulfilled' && outcome.value?.userId) {
              const doc = outcome.value;
              known.set(
                doc.userId!,
                known.get(doc.userId!) ?? {
                  userId: doc.userId!,
                  name: doc.name,
                  lastMessage: '',
                  updatedAt: '',
                  unread: 0,
                },
              );
            }
          }
        }
      }

      const sorted = [...known.values()].sort((a, b) =>
        (b.updatedAt || '').localeCompare(a.updatedAt || ''),
      );
      this.contacts.set(sorted);

      const currentId = this.selectedContact()?.userId;
      if (currentId) {
        const updatedContact = sorted.find((c) => c.userId === currentId) ?? null;
        this.selectedContact.set(updatedContact);
        if (updatedContact) await this.loadConversation();
      }
    } catch (error) {
      const msg = errorMessage(error);
      if (msg.toLowerCase().includes('suscripción')) {
        this.subscriptionRequired.set(true);
      } else {
        this.loadError.set(msg);
      }
    } finally {
      this.loadingContacts.set(false);
    }
  }

  selectContact(contact: Conversation): void {
    this.selectedContact.set(contact);
    this.message.set('');
    void this.loadConversation();
  }

  clearSelection(): void {
    this.selectedContact.set(null);
    this.messages.set([]);
    this.message.set('');
  }

  async loadConversation(): Promise<void> {
    const contact = this.selectedContact();
    if (!contact) {
      this.messages.set([]);
      return;
    }
    this.loadingThread.set(true);
    try {
      const list = await this.api.get<ChatMessage[]>(`/api/messages/${contact.userId}`);
      this.messages.set(list);
      this.contacts.update((items) =>
        items.map((item) => (item.userId === contact.userId ? { ...item, unread: 0 } : item)),
      );
      this.message.set('');
      requestAnimationFrame(() => {
        const box = document.getElementById('chat-scroll-box');
        if (box) box.scrollTop = box.scrollHeight;
      });
    } catch (error) {
      this.messages.set([]);
      this.messageTone.set('danger');
      this.message.set(errorMessage(error));
    } finally {
      this.loadingThread.set(false);
    }
  }

  async send(): Promise<void> {
    const contact = this.selectedContact();
    const content = this.content.trim();
    if (!content || !contact || this.sending()) return;
    this.sending.set(true);
    try {
      await this.api.post<ChatMessage>('/api/messages', {
        recipientId: contact.userId,
        content,
      });
      this.content = '';
      await this.loadConversation();
      this.messageTone.set('success');
      this.message.set('Mensaje enviado.');
    } catch (error) {
      this.messageTone.set('danger');
      this.message.set(errorMessage(error));
    } finally {
      this.sending.set(false);
    }
  }

  goToSubscription(): void {
    void this.router.navigate(['/panel/suscripcion']);
  }

  openEmptyAction(): void {
    void this.router.navigate([this.api.isDoctor() ? '/citas' : '/buscar']);
  }
}
